import json
import unittest
from pathlib import Path

from app.keyframe_fix import (
    build_keyframe_trim_command,
    find_first_decoded_keyframe,
    needs_keyframe_trim,
    temporary_output_path,
)


class KeyframeFixTests(unittest.TestCase):
    def test_finds_first_decoded_i_frame_with_real_packet(self):
        raw = json.dumps({"frames": [
            {"pict_type": "P", "pkt_size": "900", "best_effort_timestamp_time": "0.000"},
            {"pict_type": "I", "pkt_size": "0", "best_effort_timestamp_time": "1.000"},
            {"pict_type": "I", "pkt_size": "24500", "best_effort_timestamp_time": "2.400"},
        ]})
        self.assertEqual(find_first_decoded_keyframe(raw), (2.4, 24500))

    def test_starting_i_frame_does_not_need_trim(self):
        self.assertFalse(needs_keyframe_trim(0.0))
        self.assertFalse(needs_keyframe_trim(0.05))
        self.assertTrue(needs_keyframe_trim(0.051))

    def test_trim_is_stream_copy_to_sibling_temporary_file(self):
        source = Path("C:/video/clip.mp4")
        command, temporary = build_keyframe_trim_command(source, 1.25)
        self.assertEqual(temporary, temporary_output_path(source))
        self.assertIn("copy", command)
        self.assertNotIn("shell=True", command)
        self.assertEqual(command[-1], str(temporary))

    def test_invalid_probe_output_is_reported(self):
        with self.assertRaisesRegex(ValueError, "ffprobe"):
            find_first_decoded_keyframe("not-json")


if __name__ == "__main__":
    unittest.main()
