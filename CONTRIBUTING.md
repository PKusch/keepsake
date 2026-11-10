# Contributing

- No dependencies. Python 3.11 or later, standard library only.
- `python -m unittest discover -s tests` must pass. `python -m keepsake.corpus`
  prints the numbers the README quotes; `scripts/check_readme_numbers.py`
  checks they still match.
- A new signal needs a planted example in `corpus/planted.json` that it
  catches and a benign example in `corpus/benign.json` that it leaves alone.
  Update the pinned counts in `tests/test_corpus.py` and the README together.
- Plain words in anything a person reads: the `meaning` of a finding should
  make sense to someone who has never heard of prompt injection.
