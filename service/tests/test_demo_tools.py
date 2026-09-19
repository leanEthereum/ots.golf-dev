"""Demo controls must not let an operator seed a production site accidentally."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import seed_demo
from app.config import SERVICE_DIR
from app.visibility import visible


class DemoGuardTests(unittest.TestCase):
    def test_visibility_obeys_demo_mode_for_existing_rows(self):
        for phony in (True, False):
            with patch('app.visibility.settings', SimpleNamespace(phony=phony)):
                self.assertEqual(visible(SimpleNamespace(detail_dict={'demo': True})), phony)
                self.assertTrue(visible(SimpleNamespace(detail_dict={})))
                self.assertTrue(visible(SimpleNamespace(detail_dict={'demo': False})))

    def test_default_seed_and_refresh_command_preserve_existing_rows(self):
        config = SimpleNamespace(environment='development', base_url='http://localhost:8000',
                                 database_url=f"sqlite:///{(SERVICE_DIR / 'data').resolve() / 'ots.db'}")
        for args in ([], ['--refresh']):
            with self.subTest(args=args), patch('app.config.settings', config), \
                    patch('sys.argv', ['seed_demo.py', *args]), \
                    patch.object(seed_demo.Base.metadata, 'create_all'), \
                    patch.object(seed_demo, 'SessionLocal'), \
                    patch.object(seed_demo, 'refresh', return_value=0) as refresh, \
                    patch.object(seed_demo, 'remove') as remove:
                seed_demo.main()
                refresh.assert_called_once()
                remove.assert_not_called()

    def test_force_cannot_bypass_production_or_nonlocal_site_guard(self):
        for environment, base_url in [('production', 'https://ots.example'),
                                      ('development', 'https://ots.example')]:
            with self.subTest(environment=environment):
                config = SimpleNamespace(environment=environment, base_url=base_url)
                with patch('app.config.settings', config), patch('sys.argv', ['seed_demo.py', '--force']), \
                        patch.object(seed_demo.Base.metadata, 'create_all') as create_db:
                    with self.assertRaisesRegex(SystemExit, 'only available in development'):
                        seed_demo.main()
                    create_db.assert_not_called()


if __name__ == '__main__':
    unittest.main()
