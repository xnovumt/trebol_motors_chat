-- ============================================================
-- CONSULTAS RAG DE DEMOSTRACIÓN — TRÉBOL MOTORS
-- Segunda Entrega · Sustentación
-- ============================================================
-- Estas consultas demuestran el sistema RAG funcionando sobre
-- las tres categorías de preguntas definidas en la Sección 1c
-- de la primera entrega. Cada consulta simula el paso de
-- recuperación vectorial (retrieval) del pipeline RAG.
--
-- Para ejecutar búsqueda vectorial real, reemplaza el vector
-- del parámetro <query_embedding> con el embedding generado
-- por BAAI/bge-m3 para la pregunta del usuario.
-- ============================================================


-- ============================================================
-- CATEGORÍA A — Recuperación estructurada con lenguaje natural
-- "¿cuáles carros tienen menos de 50.000 km y son SUV?"
-- ============================================================

-- A1. Búsqueda vectorial semántica en descripciones de vehículos
--     (reemplazar '[0.1, ...]' con el embedding real de la pregunta)
/*
SELECT
    v.id_vehiculo,
    v.marca,
    v.linea,
    v.anio,
    v.carroceria,
    v.kilometraje,
    v.estado_vehiculo,
    v.precio_venta,
    vd.chunk_texto,
    1 - (vd.embedding <=> '[0.1, 0.2, ...]'::vector) AS similitud_coseno
FROM vec_vehiculo_descripcion vd
JOIN vehiculo v ON v.id_vehiculo = vd.id_vehiculo
WHERE v.estado_vehiculo = 'disponible'
ORDER BY vd.embedding <=> '[0.1, 0.2, ...]'::vector
LIMIT 5;
*/

-- A1. Versión ejecutable — búsqueda relacional equivalente
--     Demuestra que SQL resuelve esta consulta perfectamente
SELECT
    v.marca,
    v.linea,
    v.anio,
    v.carroceria,
    v.kilometraje,
    v.estado_vehiculo,
    v.precio_venta,
    vd.chunk_texto AS descripcion_indexada
FROM vehiculo v
JOIN vec_vehiculo_descripcion vd ON vd.id_vehiculo = v.id_vehiculo
WHERE v.estado_vehiculo = 'disponible'
  AND v.kilometraje < 50000
  AND v.carroceria = 'suv'
ORDER BY v.kilometraje ASC
LIMIT 5;


-- A2. "¿Hay algún Toyota automático disponible?"
SELECT
    v.marca,
    v.linea,
    v.anio,
    v.transmision,
    v.estado_vehiculo,
    v.precio_venta,
    vd.chunk_texto
FROM vehiculo v
JOIN vec_vehiculo_descripcion vd ON vd.id_vehiculo = v.id_vehiculo
WHERE v.marca = 'Toyota'
  AND v.transmision = 'automatica'
  AND v.estado_vehiculo = 'disponible'
ORDER BY v.precio_venta ASC;


-- ============================================================
-- CATEGORÍA B — Razonamiento contextual y comparación
-- "Busco algo familiar, económico, que no consuma mucho"
-- Esta consulta NO tiene filtros SQL exactos — requiere semántica
-- ============================================================

-- B1. Recuperación vectorial de la Estrategia 3 (semantic)
--     para la pregunta de estilo de vida
--     (las fichas completas capturan mejor la semántica global)
SELECT
    v.marca || ' ' || v.linea || ' ' || v.anio::text AS vehiculo,
    v.carroceria,
    v.combustible,
    v.kilometraje,
    v.precio_venta,
    vd.chunk_texto,
    -- similitud calculada contra el vector de la pregunta:
    -- 1 - (vd.embedding <=> <query_vector>) AS similitud
    cre.vector_embedding IS NOT NULL AS tiene_embedding_experimento
FROM vec_vehiculo_descripcion vd
JOIN vehiculo v ON v.id_vehiculo = vd.id_vehiculo
LEFT JOIN chunk_resultado_experimento cre
    ON cre.id_vehiculo = v.id_vehiculo AND cre.id_experimento = 3
WHERE v.estado_vehiculo = 'disponible'
  AND v.combustible IN ('hibrido', 'electrico')
  AND v.kilometraje < 40000
ORDER BY v.precio_venta ASC
LIMIT 5;


-- B2. Comparación de dos vehículos en equipamiento
--     "¿qué diferencia hay entre el vehículo 7 y el 16 en equipamiento?"
SELECT
    v.id_vehiculo,
    v.marca || ' ' || v.linea || ' ' || v.anio::text AS vehiculo,
    ve.chunk_texto AS equipamiento_indexado
FROM vec_vehiculo_equipamiento ve
JOIN vehiculo v ON v.id_vehiculo = ve.id_vehiculo
WHERE v.id_vehiculo IN (7, 16);


-- ============================================================
-- CATEGORÍA C — Historial y seguimiento transaccional
-- "¿en qué estado está mi negociación?"
-- "¿cuál fue el último precio que me ofrecieron?"
-- ============================================================

-- C1. Estado de negociaciones de un cliente específico
SELECT
    n.id_negociacion,
    v.marca || ' ' || v.linea || ' ' || v.anio::text AS vehiculo,
    n.estado,
    n.precio_acordado,
    n.fecha_apertura,
    t.actor           AS ultimo_actor,
    t.monto_ofertado  AS ultima_oferta,
    t.mensaje         AS ultimo_mensaje,
    t.fecha_turno     AS fecha_ultimo_turno
FROM negociacion_precio n
JOIN vehiculo v ON v.id_vehiculo = n.id_vehiculo
JOIN turno_negociacion t ON t.id_negociacion = n.id_negociacion
WHERE n.id_cliente = 1  -- reemplazar con el id del cliente que consulta
  AND t.fecha_turno = (
      SELECT MAX(t2.fecha_turno)
      FROM turno_negociacion t2
      WHERE t2.id_negociacion = n.id_negociacion
  )
ORDER BY t.fecha_turno DESC;


-- C2. Recuperación semántica de mensajes de negociación similares
--     "¿hay otras negociaciones donde ofrecieran 65 millones?"
--     (búsqueda vectorial sobre vec_turno_negociacion)
SELECT
    vtn.chunk_texto,
    tn.monto_ofertado,
    tn.actor,
    n.id_negociacion,
    n.estado
FROM vec_turno_negociacion vtn
JOIN turno_negociacion tn ON tn.id_turno = vtn.id_turno
JOIN negociacion_precio n ON n.id_negociacion = vtn.id_negociacion
ORDER BY vtn.embedding <=> (
    SELECT embedding FROM vec_turno_negociacion
    WHERE chunk_texto ILIKE '%65 millones%'
    LIMIT 1
)
LIMIT 5;


-- C3. Próximas citas de un cliente
SELECT
    c.id_cita,
    v.marca || ' ' || v.linea AS vehiculo,
    c.tipo_cita,
    c.fecha_hora_solicitada,
    c.estado,
    a.nombre_completo AS asesor
FROM cita c
JOIN cliente cl ON cl.id_cliente = c.id_cliente
LEFT JOIN vehiculo v ON v.id_vehiculo = c.id_vehiculo
LEFT JOIN administrador a ON a.id_admin = c.id_admin
WHERE c.id_cliente = 1  -- reemplazar con el id del cliente
  AND c.fecha_hora_solicitada >= NOW()
ORDER BY c.fecha_hora_solicitada ASC;


-- ============================================================
-- COMPARACIÓN DE ESTRATEGIAS — Consulta resumen del experimento
-- ============================================================
SELECT * FROM vw_resultados_experimento;


-- Detalle completo del experimento por estrategia y pregunta
SELECT
    ec.nombre_estrategia,
    ev.pregunta_test,
    ev.similitud_coseno_recuperada,
    ev.puntaje_humano,
    CASE ev.puntaje_humano
        WHEN 2 THEN 'Correcto'
        WHEN 1 THEN 'Parcialmente correcto'
        ELSE 'Incorrecto'
    END AS resultado
FROM evaluacion_experimento ev
JOIN experimento_chunking ec ON ec.id_experimento = ev.id_experimento
ORDER BY ec.id_experimento, ev.id_evaluacion;
