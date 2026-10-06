import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('switcher', Path(__file__).parents[1] / 'ddc-input-switch.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class TestSwitch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        fake = self.path / 'ddcutil'
        fake.write_text('''#!/usr/bin/env python3
import os, sys, json
from pathlib import Path
Path(os.environ['COMMAND_LOG']).write_text(json.dumps(sys.argv[1:]))
if os.environ.get('FAIL'):
    print('DDC communication failed', file=sys.stderr)
    sys.exit(1)
if 'getvcp' in sys.argv:
    print(os.environ.get('READ_RESULT', 'VCP 60 SNC x0f'))
''')
        fake.chmod(0o755)
        self.env = patch.dict(os.environ, {'PATH': str(self.path) + os.pathsep + os.environ['PATH'], 'COMMAND_LOG': str(self.path / 'log')})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.c = {'bus': 7, 'a': '0x0f', 'b': '0x11'}
    def test_toggle_a_to_b(self):
        m.switch(self.c, 'toggle')
        self.assertEqual((self.path / 'log').read_text(), '["setvcp", "60", "0x11", "--noverify", "--bus", "7"]')
    def test_toggle_b_to_a(self):
        with patch.dict(os.environ, {'READ_RESULT': 'VCP 60 SNC x11'}):
            self.assertIn('0x0f', m.switch(self.c, 'toggle'))
    def test_unknown_no_write(self):
        with patch.dict(os.environ, {'READ_RESULT': 'VCP 60 SNC x12'}):
            with self.assertRaisesRegex(RuntimeError, 'neither A nor B'):
                m.switch(self.c, 'toggle')
        self.assertIn('getvcp', (self.path / 'log').read_text())
    def test_failed_read(self):
        with patch.dict(os.environ, {'FAIL': '1'}):
            with self.assertRaisesRegex(RuntimeError, 'DDC communication failed'):
                m.switch(self.c, 'toggle')
    def test_explicit_does_not_read(self):
        with patch.dict(os.environ, {'READ_RESULT': 'VCP 60 ERR'}):
            self.assertIn('0x11', m.switch(self.c, 'b'))
    def test_parse_detect_excludes_invalid(self):
        out = 'Display 1\n I2C bus: /dev/i2c-7\n Mfg id: DEL - Dell\n Model: P2419H\n Serial number: ABC123\nInvalid display\n I2C bus: /dev/i2c-8\n'
        self.assertEqual(m.parse_detect(out), [{'bus': 7, 'mfg': 'DEL', 'model': 'P2419H', 'serial': 'ABC123'}])
    def test_identity(self):
        self.assertEqual(m.selector({**self.c, 'mfg': 'DEL', 'model': 'P2419H', 'serial': 'ABC'}), ['--mfg', 'DEL', '--model', 'P2419H', '--sn', 'ABC'])
    def test_input_values(self):
        self.assertEqual(m.value('0x11 — HDMI 1'), 17)
        with self.assertRaises(ValueError): m.value('256')

if __name__ == '__main__': unittest.main()
