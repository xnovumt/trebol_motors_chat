-- ============================================================
-- GROUND TRUTH — EXPERIMENTO DE CHUNKING
-- Trébol Motors · Segunda Entrega
-- ============================================================
-- Las preguntas de prueba y sus rúbricas de evaluación están
-- definidas en evaluar_experimento.py, que las ejecuta contra
-- las 3 estrategias y registra los resultados REALES (similitud
-- coseno medida + puntaje según rúbrica verificable) en la tabla
-- evaluacion_experimento.
--
-- Orden de ejecución:
--   1. entrega_2.sql            (tablas del experimento)
--   2. python pipeline_embeddings.py   (genera chunks + embeddings)
--   3. python evaluar_experimento.py   (evalúa y llena evaluacion_experimento)
--   4. Este script              (crea la vista de resultados)
-- ============================================================

-- ============================================================
-- Vista resumen de resultados por estrategia
-- ============================================================
CREATE OR REPLACE VIEW vw_resultados_experimento AS
SELECT
    e.id_experimento,
    e.nombre_estrategia,
    COUNT(ev.id_evaluacion)                                 AS total_preguntas,
    ROUND(AVG(ev.similitud_coseno_recuperada)::numeric, 4)  AS similitud_promedio,
    ROUND(AVG(ev.puntaje_humano)::numeric, 2)               AS puntaje_promedio,
    SUM(CASE WHEN ev.puntaje_humano = 2 THEN 1 ELSE 0 END)  AS respuestas_correctas,
    SUM(CASE WHEN ev.puntaje_humano = 1 THEN 1 ELSE 0 END)  AS respuestas_parciales,
    SUM(CASE WHEN ev.puntaje_humano = 0 THEN 1 ELSE 0 END)  AS respuestas_incorrectas
FROM experimento_chunking e
LEFT JOIN evaluacion_experimento ev ON ev.id_experimento = e.id_experimento
GROUP BY e.id_experimento, e.nombre_estrategia
ORDER BY similitud_promedio DESC;


-- ============================================================
-- Consultas de verificación para la sustentación
-- ============================================================

-- Resumen comparativo de las 3 estrategias
-- SELECT * FROM vw_resultados_experimento;

-- Detalle de cada pregunta evaluada
-- SELECT ec.nombre_estrategia, ev.pregunta_test,
--        ev.similitud_coseno_recuperada, ev.puntaje_humano,
--        LEFT(ev.chunk_recuperado, 60) AS chunk
-- FROM evaluacion_experimento ev
-- JOIN experimento_chunking ec USING (id_experimento)
-- ORDER BY ev.pregunta_test, ec.id_experimento;

-- Distribución de chunks generados por estrategia
-- SELECT ec.nombre_estrategia,
--        COUNT(*)                          AS total_chunks,
--        ROUND(AVG(LENGTH(cre.contenido_texto)), 1) AS longitud_promedio,
--        ROUND(COUNT(*)::numeric / 150, 2) AS chunks_por_vehiculo
-- FROM chunk_resultado_experimento cre
-- JOIN experimento_chunking ec USING (id_experimento)
-- GROUP BY ec.nombre_estrategia
-- ORDER BY ec.nombre_estrategia;
