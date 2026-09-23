"""The optional host-wide proof slot releases on exit and excludes another process."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.worker import shared_verify_slot


class SharedVerifySlotTests(unittest.TestCase):
    def test_other_process_waits_until_slot_released(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = Path(tmp) / 'slot.lock'
            probe = ('import fcntl,sys; f=open(sys.argv[1],"a"); '
                     'fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)')
            with patch.dict(os.environ, {'OTS_SHARED_VERIFY_LOCK': str(lock)}):
                with shared_verify_slot():
                    blocked = subprocess.run([sys.executable, '-c', probe, str(lock)], capture_output=True)
                    self.assertNotEqual(blocked.returncode, 0)
                acquired = subprocess.run([sys.executable, '-c', probe, str(lock)], capture_output=True)
                self.assertEqual(acquired.returncode, 0, acquired.stderr)


if __name__ == '__main__':
    unittest.main()
