"""One measured image supplies all three program-size displays."""
import json
from types import SimpleNamespace

from sqlalchemy import select

from app import records
from app.db import Submission
from app.riscv_program_size import for_submission, historical_sizes, validate
import seed_demo
import test_riscv_track
import unittest


def measurement(sub):
    return {"version": 1, "commit": sub.commit, "contract": sub.detail_dict.get("contract", "b" * 64),
            "instructions": 1337, "data_bytes": 64}


class ProgramSizeValidationTests(unittest.TestCase):
    def test_historical_measurements_are_pinned_and_recoverable_from_git(self):
        for sid, size in historical_sizes().items():
            self.assertEqual(len(sid), 32)
            self.assertEqual(validate(size, size['commit'], size['contract']), size)
        sid = '014c955e5f7e4818be9d40e746fc7456'
        size = historical_sizes()[sid]
        sub = SimpleNamespace(id=sid, track='upper-riscv', status='verified', commit=size['commit'],
                              detail_dict={'contract': size['contract']})
        self.assertEqual((for_submission(sub).instructions, for_submission(sub).data_bytes), (896, 80))
        sub.commit = '0' * 40
        self.assertIsNone(for_submission(sub))

    def setUp(self):
        self.sub = SimpleNamespace(track="upper-riscv", status="verified", commit="a" * 40,
                                   detail_dict={"contract": "b" * 64})
        self.value = measurement(self.sub)
        self.sub.detail_dict["riscv_program_size"] = self.value

    def test_instruction_count_and_data_bytes_stay_separate(self):
        size = for_submission(self.sub)
        self.assertEqual((size.instructions, size.data_bytes), (1337, 64))
        self.assertEqual((size.instruction_label, size.data_label), ("1,337", "64 B"))
        self.assertIn("Excludes runtime inputs", size.data_description)
        self.value.update(instructions=0, data_bytes=0)
        self.assertEqual(for_submission(self.sub).data_label, "0 B")

    def test_invalid_or_mismatched_metadata_never_becomes_a_size(self):
        for field, bad in [("instructions", True), ("instructions", -1), ("instructions", 262145),
                           ("data_bytes", "64"), ("data_bytes", -1), ("data_bytes", 1048577),
                           ("version", True), ("version", 2), ("commit", "c" * 40),
                           ("contract", "c" * 64)]:
            with self.subTest(field=field, bad=bad):
                value = dict(self.value)
                value[field] = bad
                self.sub.detail_dict["riscv_program_size"] = value
                self.assertIsNone(for_submission(self.sub))
        for value in [None, [], "5348", {}]:
            self.sub.detail_dict["riscv_program_size"] = value
            self.assertIsNone(for_submission(self.sub))

    def test_other_tracks_and_unverified_results_have_no_size(self):
        for status in ("pending", "verifying", "publishing", "rejected", "failed"):
            self.sub.status = status
            self.assertIsNone(for_submission(self.sub))
        self.sub.status, self.sub.track = "verified", "upper-compressions"
        self.assertIsNone(for_submission(self.sub))


class ProgramSizePageTests(test_riscv_track.RiscvTrackTests):
    def test_card_leaderboard_and_detail_use_same_record_size(self):
        seed_demo.refresh(self.session)
        sub = records.current_record(self.session, "upper-riscv")
        sub.detail = json.dumps({**sub.detail_dict, "contract": "b" * 64, "riscv_program_size": measurement(sub)})
        self.session.commit()
        page = self.client.get("/?upper=upper-riscv").text
        self.assertIn('class="card-program-size"', page)
        self.assertIn('1,337 <span>instructions</span>', page)
        self.assertIn('64 B <span>embedded data</span>', page)
        self.assertIn('>Instructions</th>', page)
        self.assertIn('>Embedded data</th>', page)
        self.assertIn('>1,337</a>', page)
        self.assertIn('>64 B</a>', page)
        self.assertNotIn('5,412 B', page)
        self.assertIn(f'/submissions/{sub.id}#program-size', page)
        detail = self.client.get(f"/submissions/{sub.id}").text
        self.assertIn('id="program-size">Instructions</dt>', detail)
        self.assertIn('id="embedded-data">Embedded data</dt>', detail)
        self.assertIn('>1,337</dd>', detail)
        self.assertIn('>64 B</dd>', detail)
        self.assertNotIn('5,412 B', detail)
        compression = records.current_record(self.session, "upper-compressions")
        self.assertNotIn('id="program-size"', self.client.get(f"/submissions/{compression.id}").text)

    def test_missing_measurement_is_not_reported_as_zero_or_borrowed(self):
        seed_demo.refresh(self.session)
        best = records.current_record(self.session, "upper-riscv")
        older = self.session.scalar(select(Submission).where(
            Submission.track == "upper-riscv", Submission.claim > best.claim).limit(1))
        older.detail = json.dumps({**older.detail_dict, "contract": "b" * 64, "riscv_program_size": measurement(older)})
        self.session.commit()
        self.assertIsNone(records.track_state(self.session, {"slug": "upper-riscv", "title": "RISC-V",
                                                           "direction": "-", "cost_unit": "cycles"})["record_program_size"])
        page = self.client.get("/").text
        self.assertNotIn('class="card-program-size"', page)
        self.assertIn('title="Program size has not been measured">–', page)
        self.assertNotIn('id="program-size"', self.client.get(f"/submissions/{best.id}").text)
