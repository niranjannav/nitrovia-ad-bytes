-- Embedding backends are now configurable (OpenRouter/NVIDIA, Ollama, OpenAI…)
-- and produce different vector dimensions, so the column becomes dimensionless
-- (no vector index at this catalog scale — retrieval is a brute-force scan).
-- embedding_model records which model produced each chunk; retrieval only
-- compares vectors from the currently configured model.

ALTER TABLE product_chunks ALTER COLUMN embedding TYPE vector;
ALTER TABLE product_chunks ADD COLUMN embedding_model text;
