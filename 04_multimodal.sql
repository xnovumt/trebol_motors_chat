-- ============================================================
-- CAPA MULTIMODAL — IMÁGENES DE VEHÍCULOS (CLIP)
-- Trébol Motors · Segunda Entrega
-- ============================================================
-- Habilita texto→imagen e imagen→imagen del diseño de la 1ª entrega.
--
-- MODELOS (espacio vectorial compartido de 512 dim):
--   - Imágenes: clip-ViT-B-32
--   - Etiquetas: clip-ViT-B-32-multilingual-v1 (texto ES alineado a CLIP)
--
-- CONJUNTO AMPLIADO: 30 imágenes reales (Wikimedia Commons) que cubren
-- los 5 colores del catálogo, los 16 modelos y varios ángulos
-- (frontal, trasera, interior) para enriquecer la búsqueda visual.
-- Las etiquetas son descripciones densas en español (color + tipo +
-- ángulo + segmento) para dar más superficie de coincidencia a las
-- consultas texto→imagen.
-- ============================================================

-- 1. Tabla de etiquetas en el espacio CLIP (512 dim)
DROP TABLE IF EXISTS vec_imagen_vehiculo_descripcion CASCADE;
CREATE TABLE vec_imagen_vehiculo_descripcion (
    id             SERIAL PRIMARY KEY,
    id_imagen      INT  NOT NULL UNIQUE REFERENCES imagen_vehiculo(id_imagen) ON DELETE CASCADE,
    chunk_texto    TEXT NOT NULL,
    embedding      vector(512) NOT NULL,
    fecha_indexado TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_vec_imagen_desc_hnsw
    ON vec_imagen_vehiculo_descripcion
    USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);

-- 2. Cargar las imágenes (cascada limpia vec_imagen_* automáticamente)
DELETE FROM imagen_vehiculo;

INSERT INTO imagen_vehiculo (id_imagen, id_vehiculo, url, orden, descripcion) VALUES
-- ---- MAZDA ----
(1,  1,  'https://upload.wikimedia.org/wikipedia/commons/thumb/b/b7/2023_Mazda_CX-5_2.0_Sport_in_Sport_Red_Crystal%2C_06-09-2024.jpg/960px-2023_Mazda_CX-5_2.0_Sport_in_Sport_Red_Crystal%2C_06-09-2024.jpg',
     1, 'Mazda CX-5 SUV color rojo brillante deportivo, vista frontal tres cuartos en exterior'),
(2,  67, 'https://upload.wikimedia.org/wikipedia/commons/thumb/a/a5/Moscow%2C_Mazda_CX-5_blue%2C_Sept_2025_02.jpg/960px-Moscow%2C_Mazda_CX-5_blue%2C_Sept_2025_02.jpg',
     1, 'Mazda CX-5 SUV azul oscuro estacionado, vista lateral en la calle'),
(3,  35, 'https://upload.wikimedia.org/wikipedia/commons/thumb/2/2a/Mazda_3_BK_sedan_01_China_2012-06-16.jpg/960px-Mazda_3_BK_sedan_01_China_2012-06-16.jpg',
     1, 'Mazda 3 sedán rojo elegante, vista frontal tres cuartos'),
(4,  81, 'https://upload.wikimedia.org/wikipedia/commons/thumb/f/f8/2006-2008_Mazda_3_%28BK_Series_2%29_Maxx_hatchback_02.jpg/960px-2006-2008_Mazda_3_%28BK_Series_2%29_Maxx_hatchback_02.jpg',
     1, 'Mazda 3 hatchback azul deportivo compacto, vista frontal'),
(5,  21, 'https://upload.wikimedia.org/wikipedia/commons/thumb/9/93/Mazda_CX-30_2.0S_2022.jpg/960px-Mazda_CX-30_2.0S_2022.jpg',
     1, 'Mazda CX-30 SUV compacta azul, vista frontal tres cuartos'),
(6,  7,  'https://upload.wikimedia.org/wikipedia/commons/thumb/d/d1/2005-2007_Mazda_2_%28DY_Series_2%29_Neo_hatchback_01.jpg/960px-2005-2007_Mazda_2_%28DY_Series_2%29_Neo_hatchback_01.jpg',
     1, 'Mazda 2 hatchback rojo compacto económico, vista frontal'),
-- ---- TOYOTA ----
(7,  38, 'https://upload.wikimedia.org/wikipedia/commons/thumb/f/ff/Toyota_Corolla_2026_interior.jpg/960px-Toyota_Corolla_2026_interior.jpg',
     1, 'interior moderno del vehículo con tablero digital, pantalla táctil y volante de cuero'),
(8,  96, 'https://upload.wikimedia.org/wikipedia/commons/thumb/6/6f/Toyota_Corolla_Cross_1.8_G_interior_20221019.jpg/960px-Toyota_Corolla_Cross_1.8_G_interior_20221019.jpg',
     1, 'interior del vehículo con consola central, palanca de cambios y asientos cómodos'),
(9,  109,'https://upload.wikimedia.org/wikipedia/commons/thumb/2/24/2018_Toyota_Corolla_%28ZRE172R%29_Ascent_sedan_%282018-11-02%29_02.jpg/960px-2018_Toyota_Corolla_%28ZRE172R%29_Ascent_sedan_%282018-11-02%29_02.jpg',
     1, 'Toyota Corolla sedán blanco familiar, vista trasera tres cuartos'),
(10, 132,'https://upload.wikimedia.org/wikipedia/commons/thumb/0/0b/Toyota_Corolla_Cross_Hybrid_1X7A1861.jpg/960px-Toyota_Corolla_Cross_Hybrid_1X7A1861.jpg',
     1, 'Toyota Corolla gris plata híbrido, vista frontal tres cuartos'),
(11, 9,  'https://upload.wikimedia.org/wikipedia/commons/thumb/8/88/Moscow%2C_Toyota_Hilux_blue%2C_Sept_2025_01.jpg/960px-Moscow%2C_Toyota_Hilux_blue%2C_Sept_2025_01.jpg',
     1, 'Toyota Hilux camioneta pickup azul oscuro doble cabina, robusta'),
(12, 62, 'https://upload.wikimedia.org/wikipedia/commons/thumb/1/15/2025_Toyota_Hilux_Travo_Prerunner_Double-Cab_2.8_Premium.jpg/960px-2025_Toyota_Hilux_Travo_Prerunner_Double-Cab_2.8_Premium.jpg',
     1, 'Toyota Hilux pickup blanca doble cabina todoterreno 4x4'),
(13, 26, 'https://upload.wikimedia.org/wikipedia/commons/thumb/f/f3/Toyota_Pickup_4x4_%28Hilux%29.jpg/960px-Toyota_Pickup_4x4_%28Hilux%29.jpg',
     1, 'Toyota Hilux pickup roja 4x4 todoterreno para trabajo'),
(14, 136,'https://upload.wikimedia.org/wikipedia/commons/thumb/d/dd/Toyota_Fortuner_White_%28cropped%29.jpg/960px-Toyota_Fortuner_White_%28cropped%29.jpg',
     1, 'Toyota Fortuner SUV grande blanca de siete puestos, familiar'),
(15, 2,  'https://upload.wikimedia.org/wikipedia/commons/thumb/a/ac/Black_Fortuner_SUV.jpg/960px-Black_Fortuner_SUV.jpg',
     1, 'Toyota Fortuner SUV negra imponente, vista frontal'),
(16, 32, 'https://upload.wikimedia.org/wikipedia/commons/thumb/1/14/2020-2024_Toyota_Yaris_Z_rear.jpg/960px-2020-2024_Toyota_Yaris_Z_rear.jpg',
     1, 'Toyota Yaris hatchback rojo pequeño, vista trasera con stop encendido'),
-- ---- CHEVROLET ----
(17, 16, 'https://upload.wikimedia.org/wikipedia/commons/thumb/2/20/2022_Chevrolet_Onix_RS_1.0_Turbo.jpg/960px-2022_Chevrolet_Onix_RS_1.0_Turbo.jpg',
     1, 'Chevrolet Onix rojo deportivo RS turbo, vista frontal tres cuartos'),
(18, 28, 'https://upload.wikimedia.org/wikipedia/commons/thumb/5/54/Chevrolet_Onix_013.jpg/960px-Chevrolet_Onix_013.jpg',
     1, 'Chevrolet Onix blanco compacto en exhibición de concesionaria'),
(19, 36, 'https://upload.wikimedia.org/wikipedia/commons/thumb/c/c6/Chevrolet_Onix_20150902-IMG_20150902_154222.JPG/960px-Chevrolet_Onix_20150902-IMG_20150902_154222.JPG',
     1, 'Chevrolet Onix azul hatchback, vista lateral'),
(20, 99, 'https://upload.wikimedia.org/wikipedia/commons/thumb/7/7e/Chevrolet_Tracker_2021_%28rear%29.png/960px-Chevrolet_Tracker_2021_%28rear%29.png',
     1, 'Chevrolet Tracker SUV azul, vista trasera tres cuartos'),
(21, 104,'https://upload.wikimedia.org/wikipedia/commons/thumb/0/03/2024_Chevrolet_Tracker_1.2_Turbo_AT.jpg/960px-2024_Chevrolet_Tracker_1.2_Turbo_AT.jpg',
     1, 'Chevrolet Tracker SUV blanca moderna turbo, vista frontal'),
(22, 42, 'https://upload.wikimedia.org/wikipedia/commons/thumb/9/9a/CHEVROLET_CAPTIVA_China.jpg/960px-CHEVROLET_CAPTIVA_China.jpg',
     1, 'Chevrolet Captiva SUV familiar grande, vista frontal'),
-- ---- RENAULT ----
(23, 148,'https://upload.wikimedia.org/wikipedia/commons/thumb/d/d3/Renault_Duster_Techroad%2C_Natal_%28DSC05979%29.jpg/960px-Renault_Duster_Techroad%2C_Natal_%28DSC05979%29.jpg',
     1, 'Renault Duster SUV blanca todoterreno, vista frontal tres cuartos'),
(24, 122,'https://upload.wikimedia.org/wikipedia/commons/thumb/b/b2/Moscow%2C_Renault_Duster_dark-grey%2C_Sept_2025_02.jpg/960px-Moscow%2C_Renault_Duster_dark-grey%2C_Sept_2025_02.jpg',
     1, 'Renault Duster SUV gris oscuro, vista lateral'),
(25, 13, 'https://upload.wikimedia.org/wikipedia/commons/thumb/1/1a/2023_Renault_Kwid_Iconic_%28Colombia%29_front_view_02.png/960px-2023_Renault_Kwid_Iconic_%28Colombia%29_front_view_02.png',
     1, 'Renault Kwid rojo compacto city car colombiano, vista frontal'),
(26, 13, 'https://upload.wikimedia.org/wikipedia/commons/thumb/5/57/2023_Renault_Kwid_Iconic_%28Colombia%29_rear_view.png/960px-2023_Renault_Kwid_Iconic_%28Colombia%29_rear_view.png',
     2, 'Renault Kwid rojo compacto, vista trasera'),
(27, 79, 'https://upload.wikimedia.org/wikipedia/commons/thumb/5/53/Renault_Kwid_%2853343921268%29.jpg/960px-Renault_Kwid_%2853343921268%29.jpg',
     1, 'Renault Kwid blanco económico, vista trasera'),
(28, 20, 'https://upload.wikimedia.org/wikipedia/commons/thumb/f/f0/Renault_Sandero_-_53522415424.jpg/960px-Renault_Sandero_-_53522415424.jpg',
     1, 'Renault Sandero hatchback plateado, vista frontal'),
(29, 144,'https://upload.wikimedia.org/wikipedia/commons/thumb/3/34/2020_Renault_Logan_Stepway_front.jpg/960px-2020_Renault_Logan_Stepway_front.jpg',
     1, 'Renault Logan Stepway sedán gris, vista frontal'),
(30, 24, 'https://upload.wikimedia.org/wikipedia/commons/thumb/a/ac/2020_Renault_Logan_Stepway_rear.jpg/960px-2020_Renault_Logan_Stepway_rear.jpg',
     1, 'Renault Logan Stepway sedán, vista trasera');

-- Ajustar la secuencia para que futuros INSERT no choquen con los ids explícitos
SELECT setval('imagen_vehiculo_id_imagen_seq', 30, true);

-- Verificación:
-- SELECT iv.id_imagen, v.marca, v.linea, v.color_exterior, iv.descripcion
-- FROM imagen_vehiculo iv JOIN vehiculo v USING(id_vehiculo) ORDER BY iv.id_imagen;
--
-- Después: python pipeline_multimodal.py  (genera los 30 embeddings CLIP)
