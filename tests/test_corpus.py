import unittest

from keepsake.corpus import summary


class Corpus(unittest.TestCase):
    """Pins the numbers the README quotes. Change the corpus, change these, change the README."""

    def test_counts(self):
        s = summary()
        self.assertEqual(s["planted_total"], 20)
        self.assertEqual(s["benign_total"], 20)

    def test_every_planted_change_reaches_its_expected_level(self):
        s = summary()
        self.assertEqual(s["planted_missed"], [])
        self.assertEqual(s["planted_caught"], 20)
        self.assertEqual(s["planted_loud"], 19)

    def test_no_benign_change_rises_above_its_allowed_level(self):
        s = summary()
        self.assertEqual(s["benign_false_alarms"], [])
        self.assertEqual(s["benign_loud"], 0)


if __name__ == "__main__":
    unittest.main()
