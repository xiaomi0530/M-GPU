"""Run: python -m unittest discover -s tools -p 'test_*.py' -v"""
import random
import tempfile
import unittest
from pathlib import Path

from framebuffer_trace import Trace, TraceTail

SAMPLE = ("MGPU_TRACE 1 4 3 01 ns\n"
          "B 10 1 0 0 3 0 0 2\n"
          "P 20 1 0 0 e0\nP 30 1 1 0 1c\nE 40 1\n"
          "B 50 2 0 0 3 0 0 2\n"
          "P 60 2 0 0 03\nP 70 2 0 0 ff\nE 80 2\nD 90 2 4\n")


def parse(text):
    model = Trace()
    for line in text.splitlines():
        model.parse_line(line)
    return model


class TraceTests(unittest.TestCase):
    def test_clear_writes_between_triangles_are_reversible(self):
        model = parse('MGPU_TRACE 1 2 1 ff ns\n'
                      'P 1 0 0 0 00\nP 2 0 1 0 00\n'
                      'B 3 1 0 0 1 0 0 0\nP 4 1 0 0 e0\nE 5 1\n'
                      'P 6 0 0 0 00\nD 7 1 4\n')
        self.assertEqual(model.seek_count(4), bytes([0, 0]))
        self.assertEqual(model.seek_count(3), bytes([224, 0]))
        self.assertEqual(model.seek_count(0), bytes([255, 255]))
        with self.assertRaises(ValueError):
            parse('MGPU_TRACE 1 2 1 00 ns\nB 1 1 0 0 1 0 0 0\nP 2 0 0 0 00\n')

    def test_overlap_undo_and_timestamp_boundaries(self):
        model = parse(SAMPLE)
        self.assertEqual(model.count_at(19), 0)
        self.assertEqual(model.count_at(20), 1)
        self.assertEqual(model.seek_count(4)[:2], bytes([255, 28]))
        self.assertEqual(model.seek_count(3)[:2], bytes([3, 28]))
        self.assertEqual(model.seek_count(2)[:2], bytes([224, 28]))
        self.assertEqual(model.seek_count(0), bytes([1]) * 12)
        self.assertEqual(model.seek_count(4), model.ingest)

    def test_isolate_excludes_other_triangles(self):
        model = parse(SAMPLE)
        self.assertEqual(model.isolated(model.by_id[2], 4)[:2], bytes([255, 1]))
        self.assertEqual(model.isolated(model.by_id[2], 2), bytes([1]) * 12)
        self.assertEqual(model.triangle_at(49).id, 1)
        self.assertEqual(model.triangle_at(50).id, 2)

    def test_random_seek_checkpoint_compaction_matches_reference(self):
        rng = random.Random(902)
        model = Trace()
        model.CHECKPOINT_STRIDE = model.checkpoint_stride = 8
        model.CHECKPOINT_BUDGET = 64
        model.parse_line("MGPU_TRACE 1 4 4 00 ns")
        model.parse_line("B 0 1 0 0 3 0 0 3")
        expected = [bytes(16)]
        frame = bytearray(16)
        for stamp in range(1, 301):
            x, y, value = rng.randrange(4), rng.randrange(4), rng.randrange(256)
            model.parse_line(f"P {stamp} 1 {x} {y} {value:02x}")
            frame[y * 4 + x] = value
            expected.append(bytes(frame))
        for _ in range(200):
            count = rng.randrange(301)
            self.assertEqual(model.seek_count(count), expected[count])
        self.assertLessEqual(len(model.checkpoints), 4)

    def test_partial_line_live_append_and_paused_state(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "live.trace"
            tail = TraceTail(path)
            self.assertFalse(tail.poll())
            self.assertFalse(tail.exists)
            path.write_bytes(SAMPLE[:SAMPLE.index("P 60") + 7].encode())
            while tail.poll(limit=11):
                pass
            self.assertIsNone(tail.error)
            self.assertEqual(len(tail.model.times), 2)
            tail.model.seek_count(1)
            with path.open("ab") as file:
                file.write(SAMPLE[SAMPLE.index("P 60") + 7:].encode())
            while tail.poll(limit=13):
                pass
            self.assertTrue(tail.model.complete)
            self.assertEqual(tail.model.cursor, 1)  # ingestion did not move playback
            self.assertEqual(tail.model.seek_count(4)[0], 255)

    def test_restart_and_malformed_log(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "live.trace"
            path.write_text(SAMPLE, encoding="ascii")
            tail = TraceTail(path)
            tail.poll()
            path.write_text("MGPU_TRACE 1 4 3 00 ns\n", encoding="ascii")
            tail.poll()
            self.assertEqual(tail.generation, 1)
            self.assertFalse(tail.model.complete)
            self.assertEqual(len(tail.model.times), 0)
            with path.open("a", encoding="ascii") as file:
                file.write("P 10 9 0 0 ff\n")
            tail.poll()
            self.assertIn("active triangle", tail.error)

    def test_reject_corrupt_events(self):
        for event in ("P 11 1 4 0 ff", "P 9 1 0 0 ff", "P 11 1 0 0 xx", "D 11 1 0"):
            with self.subTest(event=event):
                model = parse("MGPU_TRACE 1 4 3 00 ns\nB 10 1 0 0 3 0 0 2")
                with self.assertRaises(ValueError):
                    model.parse_line(event)

    def test_full_simulation_recording_matches_framebuffer(self):
        project = Path(__file__).resolve().parents[1]
        path = project / "out/studio_top/framebuffer.trace"
        if not path.exists():
            self.skipTest("Run the RTL simulation first for end-to-end comparison")
        tail = TraceTail(path)
        while tail.poll():
            pass
        self.assertIsNone(tail.error)
        self.assertTrue(tail.model.complete)
        expected = bytes(int(line, 16) for line in
                         (project / "out/studio_top/framebuffer.hex").read_text().splitlines())
        self.assertEqual(tail.model.seek_count(len(tail.model.times)), expected)
        # Check bounded, evenly spaced triangle boundaries. Replaying every
        # prefix is quadratic for board demos with tens of thousands of draws.
        triangles=tail.model.triangles
        stride=max(1,len(triangles)//32)
        targets={t.last_pixel for t in triangles[::stride]}
        targets.add(len(tail.model.times))
        frame=bytearray([tail.model.clear])*len(expected)
        previous=0
        for count in sorted(targets):
            for i in range(previous,count):
                frame[tail.model.addresses[i]]=tail.model.colors[i]
            self.assertEqual(tail.model.seek_count(count),frame)
            previous=count



if __name__ == "__main__":
    unittest.main()
