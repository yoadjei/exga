from hypothesis import settings

# derandomised so every run checks the same examples (CLAUDE.md 6: tests are deterministic);
# no example database, so nothing is written outside the repository's ignored caches
settings.register_profile("exga", derandomize=True, database=None, deadline=None, max_examples=200)
settings.load_profile("exga")
