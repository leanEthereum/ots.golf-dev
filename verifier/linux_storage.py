"""Fail-closed storage checks for the production judge's disposable work volume."""
from __future__ import annotations

import os
from pathlib import Path
import re

from contract import ContractError

MAX_WORK_BYTES = 64 * 1024 ** 3


def mount_path(value: str) -> Path:
    # mountinfo escapes whitespace and backslashes using octal bytes.
    return Path(re.sub(r"\\([0-7]{3})", lambda match: chr(int(match[1], 8)), value))


def loop_backing_file(loop: Path) -> Path | None:
    """The image file behind a loop device, from sysfs; None if unreadable or deleted."""
    try:
        with open(loop / "backing_file", encoding="utf-8") as handle:
            name = handle.read().strip()
    except OSError:
        return None
    return Path(name) if name and not name.endswith("(deleted)") else None


def image_allocation(image: Path) -> tuple[int, int]:
    """The image's apparent size and the bytes actually allocated to it on disk."""
    info = os.stat(image)
    return info.st_size, info.st_blocks * 512


def linux_work_preflight(work: Path, trusted: Path, warm_lake: Path | None = None) -> None:
    configured = os.environ.get("OTS_WORK_DIR")
    if not configured:
        raise ContractError("Linux verification requires OTS_WORK_DIR on a dedicated filesystem of at most 64 GiB")
    volume = Path(configured).resolve(strict=True)
    work = work.resolve(strict=True)
    if work == volume or not work.is_relative_to(volume):
        raise ContractError("the job directory must be beneath the mounted OTS_WORK_DIR; set TMPDIR or --work accordingly")

    mounts = []
    for line in Path("/proc/self/mountinfo").read_text().splitlines():
        before, after = line.split(" - ", 1)
        fields, filesystem = before.split(), after.split()[0]
        major, minor = map(int, fields[2].split(":"))
        mounts.append((mount_path(fields[4]), mount_path(fields[3]), filesystem, os.makedev(major, minor)))
    device = volume.stat().st_dev
    matches = [entry for entry in mounts if entry[0] == volume and entry[3] == device]
    if not matches or matches[-1][1] != Path("/"):
        raise ContractError("OTS_WORK_DIR must be the root of its own filesystem, not a directory or bind-mounted subtree")
    if matches[-1][2] not in {"ext4", "xfs", "tmpfs"}:
        raise ContractError("work storage must be a dedicated ext4, xfs or bounded tmpfs filesystem")
    if any(mount != volume and mount.is_relative_to(volume) for mount, *_ in mounts):
        raise ContractError("nested mounts inside OTS_WORK_DIR are not allowed")
    loop = Path(f"/sys/dev/block/{os.major(device)}:{os.minor(device)}/loop")
    if loop.exists():
        # A sparse image could exhaust its host filesystem before the inner volume fills, so a
        # loop-backed volume is accepted only when every byte of its image is already allocated.
        backing = loop_backing_file(loop)
        if backing is None:
            raise ContractError("cannot read the backing file of the loop-backed work volume")
        size, allocated = image_allocation(backing)
        if allocated < size:
            raise ContractError("the loop-backed work volume's image must be fully allocated (fallocate), not sparse")

    size = os.statvfs(volume)
    capacity = size.f_blocks * size.f_frsize
    if capacity <= 0 or capacity > MAX_WORK_BYTES:
        raise ContractError("the entire work filesystem must have a positive capacity of at most 64 GiB")

    state = Path(os.environ.get("OTS_DATA_DIR", str(trusted / "service" / "data")))
    protected = [Path("/"), Path.home(), trusted, state]
    if warm_lake is not None:
        protected.append(warm_lake)
    for path in protected:
        path = path.resolve()
        # New installations may not have created data/ or the warm cache yet; their
        # nearest existing ancestor identifies the filesystem they would use.
        while not path.exists() and path != path.parent:
            path = path.parent
        if path.stat().st_dev == device:
            raise ContractError(f"work storage must be separate from the system, home, trusted checkout, cache and persistent data: {path}")
