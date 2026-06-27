-- ============================================================
-- ESTRUCTURA FINAL PARA EL EXPERIMENTO DE CHUNKING (1024 DIM)
-- ============================================================

-- 1. Tabla para registrar qué estrategia se está evaluando
CREATE TABLE IF NOT EXISTS experimento_chunking (
    id_experimento INT PRIMARY KEY,
    nombre_estrategia VARCHAR(50) NOT NULL,       -- 'fixed-size', 'sentence-aware', 'semantic'
    configuracion_detallada TEXT,                  -- Parámetros del modelo y splitters
    fecha_ejecucion TIMESTAMP DEFAULT NOW()
);

-- 2. Tabla donde el script de Python guardará los chunks vectorizados
CREATE TABLE IF NOT EXISTS chunk_resultado_experimento (
    id_chunk_exp SERIAL PRIMARY KEY,
    id_experimento INT REFERENCES experimento_chunking(id_experimento) ON DELETE CASCADE,
    id_vehiculo INT REFERENCES vehiculo(id_vehiculo),
    indice_chunk INT NOT NULL,
    contenido_texto TEXT NOT NULL,
    vector_embedding vector(1024) -- Ajustado exactamente a las 1024 dimensiones de BAAI/bge-m3
);

-- 3. Tabla para almacenar la evaluación del Ground Truth
CREATE TABLE IF NOT EXISTS evaluacion_experimento (
    id_evaluacion SERIAL PRIMARY KEY,
    id_experimento INT REFERENCES experimento_chunking(id_experimento) ON DELETE CASCADE,
    pregunta_test TEXT NOT NULL,
    ground_truth TEXT NOT NULL,
    chunk_recuperado TEXT NOT NULL,
    similitud_coseno_recuperada FLOAT,
    puntaje_humano INT CHECK (puntaje_humano BETWEEN 0 AND 2) -- Escala exigida por el profesor
);