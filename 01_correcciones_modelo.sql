-- ============================================================
-- CORRECCIONES AL MODELO — SEGUNDA ENTREGA
-- Trébol Motors · PostgreSQL 15+
-- Autores: Juan Esteban Jiménez Vargas - Santiago Pérez Cardona
-- Responde a las observaciones de la revisión de la primera entrega
-- ============================================================

-- ============================================================
-- CORRECCIÓN 1
-- Inconsistencia entre modelo conceptual y lógico:
-- RETOMA.id_vehiculo_destino se modela como 1:1 opcional en el
-- ERD ("un vehículo puede ser destino de como máximo una retoma
-- activa a la vez") pero el script original no tenía UNIQUE.
-- Se agrega la restricción para que el esquema físico refleje
-- exactamente la cardinalidad declarada.
-- ============================================================
ALTER TABLE retoma
    ADD CONSTRAINT uq_retoma_vehiculo_destino
    UNIQUE (id_vehiculo_destino);


-- ============================================================
-- CORRECCIÓN 2
-- Índice compuesto faltante en BUSQUEDA_FILTRADA.
-- El esquema original ya incluye idx_vehiculo_estado,
-- idx_vehiculo_marca, idx_vehiculo_precio e idx_vehiculo_km.
-- El único índice señalado como ausente por la revisión es el
-- compuesto (id_cliente, fecha_busqueda) en busqueda_filtrada,
-- necesario para recuperar el historial de búsquedas de un
-- cliente ordenado cronológicamente desde el chatbot.
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_busqueda_cliente_fecha
    ON busqueda_filtrada (id_cliente, fecha_busqueda DESC);


-- ============================================================
-- CORRECCIÓN 3
-- Referencias polimórficas sin integridad referencial nativa.
-- INTERACCION_CHATBOT y NOTIFICACION usan el patrón
-- id_elemento_gen + tipo_elemento_gen. PostgreSQL no puede
-- verificar con FK que id_elemento_gen exista en la tabla
-- correcta. Se implementa un trigger BEFORE INSERT OR UPDATE
-- que verifica la existencia del registro referenciado según
-- el valor del discriminador, rechazando inserciones huérfanas.
-- ============================================================

-- Función de validación para INTERACCION_CHATBOT
CREATE OR REPLACE FUNCTION fn_validar_elemento_gen_interaccion()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.id_elemento_gen IS NULL THEN
        RETURN NEW;
    END IF;

    IF NEW.tipo_elemento_gen = 'CITA' THEN
        IF NOT EXISTS (SELECT 1 FROM cita WHERE id_cita = NEW.id_elemento_gen) THEN
            RAISE EXCEPTION
                'id_elemento_gen=% no existe en cita (tipo_elemento_gen=CITA)',
                NEW.id_elemento_gen;
        END IF;

    ELSIF NEW.tipo_elemento_gen = 'NEGOCIACION_PRECIO' THEN
        IF NOT EXISTS (SELECT 1 FROM negociacion_precio WHERE id_negociacion = NEW.id_elemento_gen) THEN
            RAISE EXCEPTION
                'id_elemento_gen=% no existe en negociacion_precio',
                NEW.id_elemento_gen;
        END IF;

    ELSIF NEW.tipo_elemento_gen = 'RETOMA' THEN
        IF NOT EXISTS (SELECT 1 FROM retoma WHERE id_retoma = NEW.id_elemento_gen) THEN
            RAISE EXCEPTION
                'id_elemento_gen=% no existe en retoma',
                NEW.id_elemento_gen;
        END IF;

    ELSIF NEW.tipo_elemento_gen = 'SOLICITUD_ESPECIAL' THEN
        IF NOT EXISTS (SELECT 1 FROM solicitud_especial WHERE id_solicitud = NEW.id_elemento_gen) THEN
            RAISE EXCEPTION
                'id_elemento_gen=% no existe en solicitud_especial',
                NEW.id_elemento_gen;
        END IF;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER tg_validar_interaccion_elemento_gen
    BEFORE INSERT OR UPDATE OF id_elemento_gen, tipo_elemento_gen
    ON interaccion_chatbot
    FOR EACH ROW
    EXECUTE FUNCTION fn_validar_elemento_gen_interaccion();


-- Función de validación para NOTIFICACION
CREATE OR REPLACE FUNCTION fn_validar_elemento_ref_notificacion()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.id_elemento_ref IS NULL THEN
        RETURN NEW;
    END IF;

    IF NEW.tipo_elemento_ref = 'CITA' THEN
        IF NOT EXISTS (SELECT 1 FROM cita WHERE id_cita = NEW.id_elemento_ref) THEN
            RAISE EXCEPTION 'id_elemento_ref=% no existe en cita', NEW.id_elemento_ref;
        END IF;

    ELSIF NEW.tipo_elemento_ref = 'NEGOCIACION_PRECIO' THEN
        IF NOT EXISTS (SELECT 1 FROM negociacion_precio WHERE id_negociacion = NEW.id_elemento_ref) THEN
            RAISE EXCEPTION 'id_elemento_ref=% no existe en negociacion_precio', NEW.id_elemento_ref;
        END IF;

    ELSIF NEW.tipo_elemento_ref = 'RETOMA' THEN
        IF NOT EXISTS (SELECT 1 FROM retoma WHERE id_retoma = NEW.id_elemento_ref) THEN
            RAISE EXCEPTION 'id_elemento_ref=% no existe en retoma', NEW.id_elemento_ref;
        END IF;

    ELSIF NEW.tipo_elemento_ref = 'SOLICITUD_ESPECIAL' THEN
        IF NOT EXISTS (SELECT 1 FROM solicitud_especial WHERE id_solicitud = NEW.id_elemento_ref) THEN
            RAISE EXCEPTION 'id_elemento_ref=% no existe en solicitud_especial', NEW.id_elemento_ref;
        END IF;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER tg_validar_notificacion_elemento_ref
    BEFORE INSERT OR UPDATE OF id_elemento_ref, tipo_elemento_ref
    ON notificacion
    FOR EACH ROW
    EXECUTE FUNCTION fn_validar_elemento_ref_notificacion();


-- ============================================================
-- NOTA SOBRE 3FN EN INTERACCION_CHATBOT
-- La revisión señaló que tipo_elemento_gen no depende
-- directamente de id_interaccion sino de id_elemento_gen
-- (dependencia transitiva). La solución estrictamente correcta
-- en 3FN sería usar columnas FK nulas separadas:
--   id_cita_gen INT REFERENCES cita(id_cita)
--   id_negociacion_gen INT REFERENCES negociacion_precio(id_negociacion)
--   id_retoma_gen INT REFERENCES retoma(id_retoma)
--   id_solicitud_gen INT REFERENCES solicitud_especial(id_solicitud)
-- Se mantiene el patrón discriminador por razones de usabilidad
-- operativa del chatbot (evita consultar qué columna no es NULL
-- para determinar el tipo del elemento generado), y la integridad
-- referencial queda garantizada por el trigger anterior, que
-- sustituye funcionalmente la FK nativa que PostgreSQL no puede
-- expresar con referencias polimórficas.
-- ============================================================
