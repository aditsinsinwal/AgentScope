# Deterministic evaluation

Evaluation runs public tests, verifies hashes for forbidden paths, installs hidden tests, and runs
them within the remaining deadline. The score is 70 correctness + 15 regression safety + 10
constraint adherence + 5 deadline compliance. Failed commands retain bounded stdout/stderr.

Hidden tests are the primary correctness signal, but benchmark authors must make them behaviorally
specific and independent. Tests must not rely on network, wall-clock time, random ordering, or local
machine state. Task fingerprints cover description, version, repository, and hidden test bytes.

An evaluator failure means the harness could not judge; it is not a zero-score agent result. Another
LLM may later annotate traces, but its opinion cannot change deterministic scores.

