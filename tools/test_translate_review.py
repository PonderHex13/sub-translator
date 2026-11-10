import contextlib
import io
import re
import unittest

import translate


def entry(source, target):
    return (source, re.compile(r"(?<!\w)" + re.escape(source) + r"(?!\w)", re.I), target)


class ReviewChecksTest(unittest.TestCase):
    def test_unchanged_block_ignores_case_punctuation_and_tags(self):
        self.assertEqual(
            translate.unchanged_english("<i>GOOD morning!</i>", "Good morning.", []),
            ["entire remaining text: good morning"],
        )

    def test_unchanged_words_exclude_only_keep_as_is_glossary_entries(self):
        glossary = [entry("Alan Shore", "Alan Shore"), entry("objection", "ugovor")]
        self.assertEqual(
            translate.unchanged_english("Alan Shore says objection", "Alan Shore pravi objection", glossary),
            ["objection"],
        )
        self.assertEqual(translate.unchanged_english("ALAN SHORE!", "Alan Shore.", glossary), [])

    def test_mixed_translation_flags_long_words_but_not_short_shared_words(self):
        self.assertEqual(
            translate.unchanged_english("The doctor is here", "The doctor je tukaj", []),
            ["doctor"],
        )

    def test_adjacent_phrases_and_intentional_repetition(self):
        self.assertEqual(
            translate.repeated_adjacent("He always needed", "and I always made time",
                                      "vedno je želel biti sprejet", "želel biti sprejet takoj"),
            "želel biti sprejet",
        )
        self.assertEqual(
            translate.repeated_adjacent("Thank you", "THANK YOU!", "Hvala lepa", "hvala lepa!"),
            "",
        )
        self.assertEqual(translate.repeated_adjacent("yes", "yes", "ja", "ja"), "")

    def test_report_checks_written_layout_and_includes_context(self):
        blocks = [{"num": "350"}, {"num": "351"}]
        src = ["THE DOCTOR LEFT", "HE CAME BACK"]
        final = {1: "original draft", 2: "different draft"}
        layout = [["Doctor je", "odšel naravnost domov"], ["Odšel naravnost domov", "in se vrnil"]]
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            translate.report(blocks, src, final, [], [], [], layout)
        text = output.getvalue()
        self.assertIn("block 350: doctor", text)
        self.assertIn("blocks 350-351: 'odšel naravnost domov'", text)
        self.assertIn("EN: THE DOCTOR LEFT", text)
        self.assertIn("SL: Doctor je odšel naravnost domov", text)


if __name__ == "__main__":
    unittest.main()
