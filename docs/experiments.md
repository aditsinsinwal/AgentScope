# Experiments

An experiment is a dataset/task set, agent configurations, and seed. Planning creates the complete
task × configuration matrix in stable order. Fair experiments pin task fingerprints, evaluator,
sandbox image, resource/time limits, provider model identifiers, prompt, tools, and fault policy.

Reports aggregate run count, completed count, solve/hidden-test rates, exact average score, median
and nearest-rank p95 evaluation time, and deterministic failure counts. Model and harness config are
separate so tool improvements are not attributed to a model. Compare paired task outcomes and show
confidence intervals in future reporting; AgentScope does not infer significance today.

