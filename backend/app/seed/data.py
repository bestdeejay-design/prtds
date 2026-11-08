"""Demo dataset for the local pilot environment.

⚠️ These companies, prices and contacts are **fictional**. They exist so the
team can walk the full path (search → card → WhatsApp/lead → CRM → confirmed
result → commission basis) without touching real businesses. The concept
document forbids presenting anything as live when it is not (§12), so the UI and
``/api/meta/status`` both expose a demo-data notice.

Names use Guaraní-flavoured words on purpose: they read as local but are not
real Paraguayan businesses, and they remind the team that the market is
bilingual (§02).
"""

from __future__ import annotations

from typing import Any

DEMO_NOTICE_ES = (
    "Datos de demostración del entorno local: empresas y precios ficticios "
    "para validar el recorrido. No son ofertas reales ni socios contratados."
)

SOURCES: list[dict[str, Any]] = [
    {
        "key": "manual",
        "name": "Relevamiento propio PRTDS (demo)",
        "kind": "manual",
        "url": None,
        "license_note": "Datos internos de demostración.",
        "trusted": False,
    },
    {
        "key": "partner",
        "name": "Aportado por el comercio (demo)",
        "kind": "partner",
        "url": None,
        "license_note": "Requiere confirmación del comercio antes de publicar.",
        "trusted": False,
    },
    {
        "key": "osm",
        "name": "OpenStreetMap contributors",
        "kind": "osm",
        "url": "https://www.openstreetmap.org",
        "license_note": "© OpenStreetMap contributors, ODbL.",
        "trusted": True,
    },
    {
        "key": "ine",
        "name": "INE Paraguay — EPHC 2025",
        "kind": "ine",
        "url": "https://www.ine.gov.py",
        "license_note": "Estadísticas públicas; usado solo como contexto de mercado.",
        "trusted": True,
    },
]

#: typical Paraguayan opening patterns
HOURS_PATTERNS: dict[str, dict[str, list[list[str]]]] = {
    "commercial": {
        day: [["08:00", "12:00"], ["15:00", "20:00"]]
        for day in ("mon", "tue", "wed", "thu", "fri")
    }
    | {"sat": [["08:00", "13:00"]]},
    "restaurant": {
        day: [["11:30", "15:00"], ["19:00", "23:30"]] for day in ("tue", "wed", "thu", "fri", "sat", "sun")
    },
    "24h": {day: [["00:00", "23:59"]] for day in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")},
    "supermarket": {
        day: [["07:00", "22:00"]] for day in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
    },
    "salon": {
        day: [["09:00", "19:00"]] for day in ("tue", "wed", "thu", "fri", "sat")
    },
    "office": {day: [["08:30", "17:30"]] for day in ("mon", "tue", "wed", "thu", "fri")},
}

CATEGORIES: list[dict[str, Any]] = [
    {
        "slug": "gastronomia",
        "name_es": "Gastronomía",
        "name_ru": "Гастрономия",
        "icon": "food",
        "sort_order": 10,
        "default_intent": "whatsapp",
        "children": [
            {"synonyms_es": ["comer", "almuerzo", "cena", "restaurante"], "slug": "restaurantes", "name_es": "Restaurantes", "name_ru": "Рестораны", "sort_order": 11},
            {"slug": "cafeterias", "name_es": "Cafeterías", "name_ru": "Кофейни", "sort_order": 12},
            {"slug": "delivery-comida", "name_es": "Delivery de comida", "name_ru": "Доставка еды", "sort_order": 13},
            {"slug": "bares", "name_es": "Bares y cervecerías", "name_ru": "Бары", "sort_order": 14},
        ],
    },
    {
        "slug": "supermercados",
        "name_es": "Supermercados y almacenes",
        "name_ru": "Супермаркеты и магазины",
        "icon": "cart",
        "sort_order": 20,
        "default_intent": "whatsapp",
        "children": [
            {"synonyms_es": ["compras", "mercado", "abasto", "comestibles"], "slug": "supermercados-cadena", "name_es": "Supermercados", "name_ru": "Супермаркеты", "sort_order": 21},
            {"slug": "almacenes", "name_es": "Almacenes de barrio", "name_ru": "Продуктовые лавки", "sort_order": 22},
            {"slug": "bebidas", "name_es": "Bebidas y licorerías", "name_ru": "Напитки", "sort_order": 23},
        ],
    },
    {
        "slug": "belleza",
        "name_es": "Belleza y cuidado personal",
        "name_ru": "Красота и уход",
        "icon": "sparkles",
        "sort_order": 30,
        "default_intent": "booking",
        "children": [
            {"synonyms_es": ["pelo", "cabello", "corte de pelo", "peinado"], "slug": "peluquerias", "name_es": "Peluquerías", "name_ru": "Парикмахерские", "sort_order": 31},
            {"synonyms_es": ["unas", "nails", "esmaltado", "pedicura"], "slug": "manicura", "name_es": "Manicura y uñas", "name_ru": "Маникюр", "sort_order": 32},
            {"synonyms_es": ["barba", "afeitado", "corte hombre"], "slug": "barberias", "name_es": "Barberías", "name_ru": "Барбершопы", "sort_order": 33},
            {"slug": "spa", "name_es": "Spa y masajes", "name_ru": "Спа и массаж", "sort_order": 34},
        ],
    },
    {
        "slug": "vehiculos",
        "name_es": "Vehículos",
        "name_ru": "Транспорт",
        "icon": "car",
        "sort_order": 40,
        "default_intent": "request",
        "children": [
            {"synonyms_es": ["rent a car", "alquilar auto", "arriendo vehiculo"], "slug": "alquiler-vehiculos", "name_es": "Alquiler de vehículos", "name_ru": "Аренда авто", "sort_order": 41},
            {"slug": "taller-mecanico", "name_es": "Talleres mecánicos", "name_ru": "Автосервис", "sort_order": 42},
            {"slug": "repuestos", "name_es": "Repuestos y accesorios", "name_ru": "Запчасти", "sort_order": 43},
            {"slug": "lavadero", "name_es": "Lavaderos", "name_ru": "Автомойки", "sort_order": 44},
        ],
    },
    {
        "slug": "tecnologia",
        "name_es": "Tecnología y electrodomésticos",
        "name_ru": "Техника и электроника",
        "icon": "device",
        "sort_order": 50,
        "default_intent": "whatsapp",
        "children": [
            {"synonyms_es": ["telefono", "smartphone", "movil", "celular", "iphone", "android"], "slug": "celulares", "name_es": "Celulares y accesorios", "name_ru": "Смартфоны", "sort_order": 51},
            {"slug": "informatica", "name_es": "Informática", "name_ru": "Компьютеры", "sort_order": 52},
            {"slug": "electrodomesticos", "name_es": "Electrodomésticos", "name_ru": "Бытовая техника", "sort_order": 53},
        ],
    },
    {
        "slug": "salud",
        "name_es": "Salud",
        "name_ru": "Здоровье",
        "icon": "health",
        "sort_order": 60,
        "default_intent": "call",
        "children": [
            {"synonyms_es": ["medicamentos", "remedios", "farmacia de turno"], "slug": "farmacias", "name_es": "Farmacias", "name_ru": "Аптеки", "sort_order": 61},
            {"slug": "clinicas", "name_es": "Clínicas y consultorios", "name_ru": "Клиники", "sort_order": 62},
            {"slug": "odontologia", "name_es": "Odontología", "name_ru": "Стоматология", "sort_order": 63},
        ],
    },
    {
        "slug": "hogar",
        "name_es": "Hogar y construcción",
        "name_ru": "Дом и строительство",
        "icon": "home",
        "sort_order": 70,
        "default_intent": "whatsapp",
        "children": [
            {"slug": "ferreteria", "name_es": "Ferreterías", "name_ru": "Хозтовары", "sort_order": 71},
            {"slug": "muebles", "name_es": "Muebles y decoración", "name_ru": "Мебель", "sort_order": 72},
        ],
    },
    {
        "slug": "educacion",
        "name_es": "Educación",
        "name_ru": "Образование",
        "icon": "book",
        "sort_order": 80,
        "default_intent": "request",
        "children": [
            {"slug": "idiomas", "name_es": "Idiomas", "name_ru": "Языки", "sort_order": 81},
            {"slug": "apoyo-escolar", "name_es": "Apoyo escolar", "name_ru": "Репетиторы", "sort_order": 82},
        ],
    },
    {
        "slug": "servicios",
        "name_es": "Servicios profesionales",
        "name_ru": "Услуги",
        "icon": "briefcase",
        "sort_order": 90,
        "default_intent": "request",
        "children": [
            {"slug": "contadores", "name_es": "Contadores y trámites", "name_ru": "Бухгалтерия", "sort_order": 91},
            {"synonyms_es": ["flete", "mudanza", "transporte de muebles"], "slug": "mudanzas", "name_es": "Mudanzas y fletes", "name_ru": "Переезды", "sort_order": 92},
            {"slug": "abogados", "name_es": "Abogados", "name_ru": "Юристы", "sort_order": 93},
        ],
    },
    {
        "slug": "eventos",
        "name_es": "Eventos y agenda",
        "name_ru": "События и афиша",
        "icon": "ticket",
        "sort_order": 100,
        "default_intent": "request",
        "children": [
            {"slug": "shows", "name_es": "Shows y música en vivo", "name_ru": "Концерты", "sort_order": 101},
            {"slug": "teatro", "name_es": "Teatro", "name_ru": "Театр", "sort_order": 102},
        ],
    },
    {
        "slug": "turismo",
        "name_es": "Turismo y alojamiento",
        "name_ru": "Туризм и проживание",
        "icon": "bed",
        "sort_order": 110,
        "default_intent": "booking",
        "children": [
            {"synonyms_es": ["alojamiento", "hospedaje", "habitacion"], "slug": "hoteles", "name_es": "Hoteles", "name_ru": "Отели", "sort_order": 111},
            {"slug": "excursiones", "name_es": "Excursiones", "name_ru": "Экскурсии", "sort_order": 112},
        ],
    },
    {
        "slug": "mascotas",
        "name_es": "Mascotas",
        "name_ru": "Животные",
        "icon": "paw",
        "sort_order": 120,
        "default_intent": "booking",
        "children": [
            {"slug": "veterinarias", "name_es": "Veterinarias", "name_ru": "Ветклиники", "sort_order": 121},
            {"slug": "pet-shops", "name_es": "Pet shops", "name_ru": "Зоомагазины", "sort_order": 122},
        ],
    },
]


def _branch(
    name: str,
    barrio: str,
    *,
    city: str = "Asunción",
    address: str | None = None,
    phone: str | None = None,
    whatsapp: str | None = None,
    has_whatsapp: bool = True,
    lat: float | None = None,
    lng: float | None = None,
    hours: str = "commercial",
    pickup: bool = True,
    delivery: bool = False,
    delivery_fee: int = 0,
    delivery_zone: str | None = None,
    status: str = "published",
) -> dict[str, Any]:
    return {
        "name_es": name,
        "barrio": barrio,
        "city": city,
        "address_text": address or f"{barrio}, {city}",
        "phone_e164": phone,
        "whatsapp_e164": whatsapp or (phone if has_whatsapp else None),
        "latitude": lat,
        "longitude": lng,
        "opening_hours": HOURS_PATTERNS.get(hours, HOURS_PATTERNS["commercial"]),
        "pickup_available": pickup,
        "delivery_available": delivery,
        "delivery_fee_pyg": delivery_fee,
        "delivery_zone_es": delivery_zone,
        "publication_status": status,
    }


def _offer(
    title: str,
    price: int,
    *,
    unit: str | None = None,
    sku: str | None = None,
    discount: int = 0,
    availability: str = "in_stock",
    description: str | None = None,
    attributes: dict | None = None,
) -> dict[str, Any]:
    return {
        "title_es": title,
        "base_price": price,
        "unit": unit,
        "sku": sku,
        "seller_discount": discount,
        "availability_status": availability,
        "description_es": description,
        "attributes": attributes,
    }


COMPANIES: list[dict[str, Any]] = [
    {
        "slug": "parrilla-yvoty",
        "display_name": "Parrilla Yvoty",
        "category": "restaurantes",
        "extra_categories": ["delivery-comida"],
        "short": "Parrilla familiar: cortes a la parrilla, menú del día y guarniciones.",
        "description": "Restaurante de barrio con atención de martes a domingo. Acepta reservas para grupos.",
        "brand": "Parrilla Yvoty",
        "legal": {"name": "Parrilla Yvoty S.A.", "ruc": "80011001-1"},
        "verification": "partner_confirmed",
        "branches": [
            _branch("Casa central — Centro", "Centro", phone="+595215550101", lat=-25.2966, lng=-57.6351, hours="restaurant", delivery=True, delivery_fee=25_000, delivery_zone="Centro, La Encarnación"),
            _branch("Sucursal Villa Morra", "Villa Morra", phone="+595215550102", lat=-25.2954, lng=-57.5914, hours="restaurant", delivery=True, delivery_fee=30_000, delivery_zone="Villa Morra, Recoleta"),
        ],
        "offers": [
            _offer("Parrillada para 2 personas", 185_000, unit="porción", sku="YV-PAR-2", description="Corte mixto, guarnición y salsa de la casa."),
            _offer("Bife ancho 400 g", 95_000, unit="plato", sku="YV-BIF-400"),
            _offer("Menú del día (almuerzo)", 42_000, unit="menú", sku="YV-MEN-DIA", availability="in_stock"),
            _offer("Chipa guasú casera", 18_000, unit="porción", sku="YV-CHI-GUA"),
        ],
    },
    {
        "slug": "cafe-kuratuu",
        "display_name": "Café Kuratũ",
        "category": "cafeterias",
        "short": "Café de especialidad, medialunas y tortilla paraguaya.",
        "brand": "Café Kuratũ",
        "legal": {"name": "Kuratũ Gastronomía E.I.R.L.", "ruc": "80011002-2"},
        "verification": "field_verified",
        "branches": [
            _branch("Local Villa Morra", "Villa Morra", phone="+595215550201", lat=-25.2989, lng=-57.5869, hours="commercial", pickup=True, delivery=False),
        ],
        "offers": [
            _offer("Café con leche + 3 medialunas", 28_000, unit="combo", sku="CK-COM-01"),
            _offer("Tortilla paraguaya (porción)", 15_000, unit="porción", sku="CK-TOR-01"),
            _offer("Café de especialidad 250 g (granos)", 68_000, unit="paquete", sku="CK-GRA-250", availability="on_request"),
        ],
    },
    {
        "slug": "sushi-mbokaja",
        "display_name": "Sushi Mbokajá",
        "category": "delivery-comida",
        "short": "Sushi y comida japonesa con delivery propio en Asunción.",
        "brand": "Sushi Mbokajá",
        "legal": {"name": "Mbokajá Food S.R.L.", "ruc": "80011003-3"},
        "verification": "partner_confirmed",
        "branches": [
            _branch("Cocina Recoleta", "Recoleta", phone="+595215550301", lat=-25.2884, lng=-57.6118, hours="restaurant", pickup=False, delivery=True, delivery_fee=20_000, delivery_zone="Recoleta, Centro, Villa Morra"),
        ],
        "offers": [
            _offer("Combo sushi 24 piezas", 145_000, unit="combo", sku="SM-COM-24"),
            _offer("Combo sushi 12 piezas", 78_000, unit="combo", sku="SM-COM-12"),
            _offer("Yakimeshi de pollo", 55_000, unit="plato", sku="SM-YAK-POL"),
        ],
    },
    {
        "slug": "supermercado-kaaguy",
        "display_name": "Supermercado Ka'aguy",
        "category": "supermercados-cadena",
        "short": "Cadena de supermercados: almacén, carnicería, verdulería y limpieza.",
        "brand": "Ka'aguy",
        "legal": {"name": "Distribuidora Ka'aguy S.A.", "ruc": "80011004-4"},
        "verification": "field_verified",
        "branches": [
            _branch("Ka'aguy Centro", "Centro", phone="+595215550401", lat=-25.3006, lng=-57.6398, hours="supermarket", delivery=True, delivery_fee=35_000, delivery_zone="Centro y alrededores"),
            _branch("Ka'aguy Sajonia", "Sajonia", phone="+595215550402", lat=-25.3022, lng=-57.6610, hours="supermarket", delivery=True, delivery_fee=35_000, delivery_zone="Sajonia, Tacumbú"),
            _branch("Ka'aguy Trinidad", "Santísima Trinidad", phone="+595215550403", lat=-25.2686, lng=-57.6279, hours="supermarket"),
        ],
        "offers": [
            _offer("Yerba mate tradicional 1 kg", 32_000, unit="paquete", sku="KA-YER-1000", attributes={"barcode": "7841000000017", "brand_demo": "Yerba Ita"}),
            _offer("Aceite de girasol 900 ml", 12_500, unit="botella", sku="KA-ACE-900"),
            _offer("Pollo entero (por kg)", 24_000, unit="kg", sku="KA-POL-KG", availability="in_stock"),
            _offer("Pan francés (por kg)", 14_000, unit="kg", sku="KA-PAN-KG"),
            _offer("Detergente en polvo 800 g", 18_900, unit="caja", sku="KA-DET-800", discount=1_900),
            _offer("Gaseosa cola 2 L", 9_800, unit="botella", sku="KA-GAS-2L"),
        ],
    },
    {
        "slug": "almacen-dona-nidia",
        "display_name": "Almacén Doña Nidia",
        "category": "almacenes",
        "short": "Almacén de barrio: fideos, aceite, limpieza y fiambres al corte.",
        "legal": {"name": "Nidia Ramírez (persona física)", "ruc": "1099887-7"},
        "verification": "source_only",
        "branches": [
            _branch("Local Trinidad", "Santísima Trinidad", phone="+595981555401", lat=-25.2671, lng=-57.6202, hours="commercial", pickup=True, delivery=False),
        ],
        "offers": [
            _offer("Fideos secos 500 g", 6_800, unit="paquete", sku="DN-FID-500"),
            _offer("Gaseosa 2 L (segunda marca)", 7_500, unit="botella", sku="DN-GAS-2L"),
            _offer("Jamón cocido (por kg)", 62_000, unit="kg", sku="DN-JAM-KG", availability="on_request"),
        ],
    },
    {
        "slug": "peluqueria-pora",
        "display_name": "Peluquería Porã",
        "category": "peluquerias",
        "short": "Corte, coloración y tratamientos. Atención con turno.",
        "brand": "Porã",
        "legal": {"name": "Porã Estética S.R.L.", "ruc": "80011006-6"},
        "verification": "partner_confirmed",
        "branches": [
            _branch("Salón Villa Morra", "Villa Morra", phone="+595215550601", lat=-25.2940, lng=-57.5882, hours="salon"),
        ],
        "offers": [
            _offer("Corte + lavado (mujer)", 60_000, unit="servicio", sku="PO-COR-MUJ"),
            _offer("Coloración completa", 250_000, unit="servicio", sku="PO-COL-COM", availability="on_request"),
            _offer("Corte (hombre)", 45_000, unit="servicio", sku="PO-COR-HOM"),
        ],
    },
    {
        "slug": "nails-mburucuya",
        "display_name": "Nails Mburucuyá",
        "category": "manicura",
        "short": "Manicura, pedicura y uñas esculpidas. Turnos por WhatsApp.",
        "brand": "Nails Mburucuyá",
        "legal": {"name": "Mburucuyá Beauty E.I.R.L.", "ruc": "80011007-7"},
        "verification": "partner_confirmed",
        "branches": [
            _branch("Estudio Las Mercedes", "Las Mercedes", phone="+595982555601", lat=-25.2911, lng=-57.6173, hours="salon"),
        ],
        "offers": [
            _offer("Manicura clásica", 70_000, unit="servicio", sku="NM-MAN-CLA"),
            _offer("Uñas esculpidas (set completo)", 180_000, unit="servicio", sku="NM-ESC-SET"),
            _offer("Pedicura spa", 95_000, unit="servicio", sku="NM-PED-SPA"),
        ],
    },
    {
        "slug": "barberia-ypacarai",
        "display_name": "Barbería Ypacaraí",
        "category": "barberias",
        "short": "Corte masculino, barba y afeitado clásico.",
        "legal": {"name": "Ypacaraí Barber E.I.R.L.", "ruc": "80011008-8"},
        "verification": "source_only",
        "branches": [
            _branch("Local Sajonia", "Sajonia", phone="+595983555701", lat=-25.3039, lng=-57.6540, hours="salon"),
        ],
        "offers": [
            _offer("Corte masculino", 40_000, unit="servicio", sku="BY-COR-MAS"),
            _offer("Arreglo de barba", 25_000, unit="servicio", sku="BY-BAR-ARR"),
            _offer("Corte + barba", 58_000, unit="combo", sku="BY-COM-CB"),
        ],
    },
    {
        "slug": "rentcar-terere",
        "display_name": "RentCar Tereré",
        "category": "alquiler-vehiculos",
        "short": "Alquiler de autos económicos, SUV y vans con entrega en Asunción.",
        "brand": "RentCar Tereré",
        "legal": {"name": "Tereré Movilidad S.A.", "ruc": "80011009-9"},
        "verification": "partner_confirmed",
        "branches": [
            _branch("Oficina Centro", "Centro", phone="+595215550801", lat=-25.2999, lng=-57.6319, hours="commercial", pickup=True, delivery=True, delivery_fee=60_000, delivery_zone="Asunción y Gran Asunción"),
            _branch("Punto Luque", "Luque", city="Luque", phone="+595215550802", lat=-25.2708, lng=-57.4906, hours="commercial"),
        ],
        "offers": [
            _offer("Auto económico — por día", 350_000, unit="día", sku="RT-ECO-DIA", attributes={"transmission": "manual", "seats": 5}),
            _offer("SUV — fin de semana (2 días)", 900_000, unit="2 días", sku="RT-SUV-2D", attributes={"transmission": "automática", "seats": 5}),
            _offer("Van familiar — por día", 650_000, unit="día", sku="RT-VAN-DIA", attributes={"seats": 8}),
            _offer("Entrega y retiro en el aeropuerto", 120_000, unit="servicio", sku="RT-AIR-ENT", availability="on_request"),
        ],
    },
    {
        "slug": "taller-nanduti",
        "display_name": "Taller Mecánico Ñandutí",
        "category": "taller-mecanico",
        "short": "Mecánica ligera, cambio de aceite, frenos y alineación.",
        "legal": {"name": "Ñandutí Automotores E.I.R.L.", "ruc": "80011010-0"},
        "verification": "source_only",
        "branches": [
            _branch("Taller Lambaré", "Lambaré", city="Lambaré", phone="+595215550901", lat=-25.3386, lng=-57.6200, hours="commercial", pickup=True, delivery=False),
        ],
        "offers": [
            _offer("Cambio de aceite y filtro", 280_000, unit="servicio", sku="TA-OIL-CAM"),
            _offer("Alineación y balanceo", 220_000, unit="servicio", sku="TA-ALI-BAL"),
            _offer("Revisión de frenos", 150_000, unit="servicio", sku="TA-FRE-REV"),
        ],
    },
    {
        "slug": "tecnomovil-guarani",
        "display_name": "TecnoMóvil Guaraní",
        "category": "celulares",
        "extra_categories": ["electrodomesticos"],
        "short": "Celulares, accesorios y servicio técnico. Precios en guaraníes, garantía local.",
        "brand": "TecnoMóvil Guaraní",
        "legal": {"name": "TecnoMóvil Guaraní S.A.", "ruc": "80011011-1"},
        "verification": "partner_confirmed",
        "promoted": True,
        "branches": [
            _branch("Local Centro", "Centro", phone="+595215551001", lat=-25.2977, lng=-57.6371, hours="commercial", delivery=True, delivery_fee=25_000, delivery_zone="Asunción"),
            _branch("Local San Lorenzo", "San Lorenzo", city="San Lorenzo", phone="+595215551002", lat=-25.3289, lng=-57.5339, hours="commercial"),
        ],
        "offers": [
            _offer("Smartphone gama media 128 GB", 1_650_000, unit="unidad", sku="TG-SM-128", discount=50_000, attributes={"warranty_months": 12}),
            _offer("Auriculares bluetooth", 240_000, unit="unidad", sku="TG-AUR-BT"),
            _offer("Funda + vidrio templado", 65_000, unit="kit", sku="TG-KIT-FV"),
            _offer("Smart TV 43\" 4K", 2_850_000, unit="unidad", sku="TG-TV-43", availability="on_request"),
        ],
    },
    {
        "slug": "infocenter-yvyra",
        "display_name": "InfoCenter Yvyrá",
        "category": "informatica",
        "short": "Notebooks, impresoras, insumos y soporte para oficinas.",
        "legal": {"name": "Yvyrá Informática S.R.L.", "ruc": "80011012-2"},
        "verification": "partner_confirmed",
        "branches": [
            _branch("Showroom Villa Morra", "Villa Morra", phone="+595215551101", lat=-25.2925, lng=-57.5801, hours="commercial", delivery=True, delivery_fee=30_000, delivery_zone="Asunción"),
        ],
        "offers": [
            _offer("Notebook 8 GB / 256 GB SSD", 3_900_000, unit="unidad", sku="IY-NB-8-256"),
            _offer("Impresora multifunción", 1_250_000, unit="unidad", sku="IY-IMP-MUL"),
            _offer("Resma de papel A4 (500 hojas)", 45_000, unit="resma", sku="IY-PAP-A4"),
        ],
    },
    {
        "slug": "farmacia-ysapy",
        "display_name": "Farmacia Ysapy",
        "category": "farmacias",
        "short": "Farmacia de turno con delivery y medicamentos de venta libre.",
        "brand": "Ysapy",
        "legal": {"name": "Farmacias Ysapy S.A.", "ruc": "80011013-3"},
        "verification": "field_verified",
        "branches": [
            _branch("Farmacia Recoleta (24 h)", "Recoleta", phone="+595215551201", lat=-25.2862, lng=-57.6062, hours="24h", pickup=True, delivery=True, delivery_fee=15_000, delivery_zone="Recoleta, Centro, Villa Morra"),
            _branch("Farmacia Barrio Jara", "Barrio Jara", phone="+595215551202", lat=-25.2900, lng=-57.6250, hours="commercial"),
        ],
        "offers": [
            _offer("Paracetamol 500 mg x 20", 12_000, unit="caja", sku="FY-PAR-500"),
            _offer("Vitamina C efervescente", 35_000, unit="tubo", sku="FY-VIT-C"),
            _offer("Alcohol en gel 500 ml", 22_000, unit="frasco", sku="FY-ALC-500"),
        ],
    },
    {
        "slug": "clinica-mborayhu",
        "display_name": "Clínica Mborayhu",
        "category": "clinicas",
        "short": "Consultas clínicas, chequeos y laboratorio básico.",
        "legal": {"name": "Clínica Mborayhu S.A.", "ruc": "80011014-4"},
        "verification": "partner_confirmed",
        "branches": [
            _branch("Sede Asunción", "Centro", phone="+595215551301", lat=-25.3015, lng=-57.6295, hours="commercial", has_whatsapp=False),
        ],
        "offers": [
            _offer("Consulta clínica", 150_000, unit="consulta", sku="CM-CON-CLI"),
            _offer("Chequeo básico + laboratorio", 450_000, unit="estudio", sku="CM-CHE-BAS", availability="on_request"),
        ],
    },
    {
        "slug": "ferreteria-ita",
        "display_name": "Ferretería Itá",
        "category": "ferreteria",
        "short": "Herramientas, pintura, eléctricos y materiales de construcción.",
        "legal": {"name": "Itá Ferretería E.I.R.L.", "ruc": "80011015-5"},
        "verification": "source_only",
        "branches": [
            _branch("Depósito San Lorenzo", "San Lorenzo", city="San Lorenzo", phone="+595215551401", lat=-25.3315, lng=-57.5282, hours="commercial", pickup=True, delivery=True, delivery_fee=40_000, delivery_zone="San Lorenzo, Fernando de la Mora"),
        ],
        "offers": [
            _offer("Taladro percutor 650 W", 480_000, unit="unidad", sku="FI-TAL-650"),
            _offer("Juego de destornilladores (6 pzas)", 65_000, unit="juego", sku="FI-DES-6"),
            _offer("Cemento 50 kg", 58_000, unit="bolsa", sku="FI-CEM-50"),
            _offer("Pintura látex interior 18 L", 320_000, unit="balde", sku="FI-PIN-18", availability="on_request"),
        ],
    },
    {
        "slug": "instituto-neengatu",
        "display_name": "Instituto Ñe'ẽngatú",
        "category": "idiomas",
        "short": "Cursos de inglés y guaraní, presenciales y en línea.",
        "legal": {"name": "Instituto Ñe'ẽngatú E.I.R.L.", "ruc": "80011016-6"},
        "verification": "partner_confirmed",
        "branches": [
            _branch("Sede Centro", "Centro", phone="+595215551501", lat=-25.2958, lng=-57.6341, hours="office"),
        ],
        "offers": [
            _offer("Curso de inglés — mensual", 380_000, unit="mes", sku="IN-ING-MES"),
            _offer("Curso de guaraní — mensual", 250_000, unit="mes", sku="IN-GUA-MES"),
            _offer("Clase de conversación (4 sesiones)", 180_000, unit="pack", sku="IN-CON-4"),
        ],
    },
    {
        "slug": "agenda-yvoty-shows",
        "display_name": "Agenda Yvoty Shows",
        "category": "shows",
        "short": "Organizador de eventos: shows en vivo, festivales y teatro.",
        "legal": {"name": "Yvoty Producciones S.A.", "ruc": "80011017-7"},
        "verification": "partner_confirmed",
        "branches": [
            _branch("Oficina de producción", "Manorá", phone="+595215551601", lat=-25.2790, lng=-57.6100, hours="office", pickup=False, delivery=False, has_whatsapp=False),
        ],
        "offers": [
            _offer("Entrada general — show en vivo", 90_000, unit="entrada", sku="AY-ENT-GEN", availability="in_stock"),
            _offer("Entrada sector preferencial", 180_000, unit="entrada", sku="AY-ENT-PRE"),
            _offer("Entrada gratuita — evento cultural", 0, unit="entrada", sku="AY-ENT-LIB", availability="seasonal"),
        ],
    },
    {
        "slug": "estudio-contable-aty",
        "display_name": "Estudio Contable Aty",
        "category": "contadores",
        "short": "Asesoría contable, inscripción de RUC e IVA para pymes.",
        "legal": {"name": "Aty Servicios Contables S.R.L.", "ruc": "80011018-8"},
        "verification": "partner_confirmed",
        "branches": [
            _branch("Oficina Centro", "Centro", phone="+595215551701", lat=-25.3020, lng=-57.6410, hours="office", pickup=False, delivery=False, has_whatsapp=False),
        ],
        "offers": [
            _offer("Asesoría mensual para pyme", 750_000, unit="mes", sku="AC-ASE-PYM"),
            _offer("Inscripción RUC (trámite completo)", 180_000, unit="trámite", sku="AC-RUC-INS"),
        ],
    },
    {
        "slug": "mudanzas-ypytu",
        "display_name": "Mudanzas Ypytũ",
        "category": "mudanzas",
        "short": "Mudanzas de departamentos, oficinas y fletes dentro del Gran Asunción.",
        "legal": {"name": "Ypytũ Logística E.I.R.L.", "ruc": "80011019-9"},
        "verification": "source_only",
        "branches": [
            _branch("Base Fernando de la Mora", "Fernando de la Mora", city="Fernando de la Mora", phone="+5959845551801", lat=-25.3160, lng=-57.5830, hours="commercial", pickup=False, delivery=True, delivery_fee=0, delivery_zone="Gran Asunción"),
        ],
        "offers": [
            _offer("Mudanza departamento 1 dormitorio", 950_000, unit="servicio", sku="MU-DEP-1", availability="on_request"),
            _offer("Flete dentro de Asunción", 220_000, unit="servicio", sku="MU-FLE-ASU"),
        ],
    },
    {
        "slug": "hotel-parana-mboy",
        "display_name": "Hotel Paraná Mboy",
        "category": "hoteles",
        "short": "Hotel céntrico: habitaciones dobles, desayuno buffet y sala de reuniones.",
        "legal": {"name": "Paraná Mboy Hotelería S.A.", "ruc": "80011020-0"},
        "verification": "partner_confirmed",
        "branches": [
            _branch("Hotel Centro", "Centro", phone="+595215551901", lat=-25.2991, lng=-57.6265, hours="24h", pickup=False, delivery=False),
        ],
        "offers": [
            _offer("Habitación doble — por noche", 380_000, unit="noche", sku="HP-DOB-NOC"),
            _offer("Desayuno buffet", 45_000, unit="persona", sku="HP-DES-BUF"),
            _offer("Sala de reuniones (por hora)", 120_000, unit="hora", sku="HP-SAL-HOR", availability="on_request"),
        ],
    },
    {
        "slug": "veterinaria-jaguarete",
        "display_name": "Veterinaria Jaguarete",
        "category": "veterinarias",
        "extra_categories": ["pet-shops"],
        "short": "Consultas, vacunas, baño y corte; alimentos y accesorios para mascotas.",
        "legal": {"name": "Jaguarete Veterinaria E.I.R.L.", "ruc": "80011021-1"},
        "verification": "partner_confirmed",
        "branches": [
            _branch("Clínica Villa Morra", "Villa Morra", phone="+595215552001", lat=-25.2933, lng=-57.5897, hours="salon", delivery=True, delivery_fee=20_000, delivery_zone="Villa Morra, Recoleta"),
        ],
        "offers": [
            _offer("Consulta veterinaria", 120_000, unit="consulta", sku="VJ-CON-VET"),
            _offer("Vacuna antirrábica", 80_000, unit="dosis", sku="VJ-VAC-ANT"),
            _offer("Baño y corte (perro mediano)", 110_000, unit="servicio", sku="VJ-BAN-COR"),
            _offer("Alimento premium 15 kg", 480_000, unit="bolsa", sku="VJ-ALI-15"),
        ],
    },
    # --- pipeline examples: NOT published, must not appear in search ----------
    {
        "slug": "bodega-mboriahu-staging",
        "display_name": "Bodega Mboriahu (en validación)",
        "category": "bebidas",
        "short": "Registro en staging: falta confirmar precios y horarios con el comercio.",
        "legal": {"name": "Bodega Mboriahu E.I.R.L.", "ruc": "80011099-9"},
        "verification": "unverified",
        "status": "staging",
        "branches": [
            _branch("Local en validación", "Mariano Roque Alonso", city="Mariano Roque Alonso", phone="+5959855550991", hours="commercial", status="staging"),
        ],
        "offers": [_offer("Cerveza 6 pack", 48_000, unit="pack", sku="BM-CER-6", availability="on_request")],
    },
    {
        "slug": "taller-registro-maestro",
        "display_name": "Taller sin ficha (solo registro maestro)",
        "category": "taller-mecanico",
        "short": "Fila del registro de personas jurídicas: todavía no es una ficha pública.",
        "legal": {"name": "Taller Mbarete S.A.", "ruc": "80011098-8"},
        "verification": "source_only",
        "status": "draft",
        "branches": [],
        "offers": [],
    },
]

#: registry rows that never became cards — the §15 distinction in data form
EXTRA_LEGAL_ENTITIES: list[dict[str, Any]] = [
    {"name": "Comercial Ysyry S.A.", "ruc": "80099001-1"},
    {"name": "Servicios Yvate E.I.R.L.", "ruc": "80099002-2"},
    {"name": "Importadora Ka'arendá S.R.L.", "ruc": "80099003-3"},
]

BENEFIT_RULES: list[dict[str, Any]] = [
    {
        "code": "TECNO-PROMO-10",
        "source_kind": "seller",
        "financier": "TecnoMóvil Guaraní (demo)",
        "presentation_type": "promo_code",
        "company_slug": "tecnomovil-guarani",
        "kind": "percent",
        "value_bps": 1000,
        "cap_amount_pyg": 150_000,
        "guaranteed": True,
        "is_conditional": False,
        "conditions_es": "Descuento del comercio en celulares seleccionados. Válido hasta agotar stock.",
    },
    {
        "code": "BANCO-DEMO-VIE-15",
        "source_kind": "bank",
        "financier": "Banco de ejemplo (piloto, no contratado)",
        "presentation_type": "bank_card",
        "company_slug": "tecnomovil-guarani",
        "kind": "cashback_percent",
        "value_bps": 1500,
        "cap_amount_pyg": 200_000,
        "guaranteed": False,
        "is_conditional": True,
        "conditions_es": (
            "Reintegro los viernes con tarjeta del banco de ejemplo, sujeto a tope mensual "
            "personal que PRTDS no conoce: se muestra como beneficio potencial, nunca como "
            "precio final garantizado."
        ),
    },
    {
        "code": "MARCA-YERBA-2000",
        "source_kind": "manufacturer",
        "financier": "Marca de yerba (demo)",
        "presentation_type": "promo_code",
        "category_slug": "supermercados-cadena",
        "kind": "fixed",
        "fixed_amount_pyg": 2_000,
        "cap_amount_pyg": 2_000,
        "guaranteed": True,
        "is_conditional": False,
        "conditions_es": "Aporte del fabricante por unidad de yerba mate 1 kg durante la campaña.",
    },
]

COMMISSION_RULES: list[dict[str, Any]] = [
    {
        "name": "Global — 5% venta confirmada",
        "scope": "global",
        "applies_to": "sale_confirmed",
        "rate_percent": 5.0,
        "priority": 900,
        "notes": "Regla por defecto para contratos activos sin regla propia. Orientativa, no tarifaria.",
    },
    {
        "name": "Belleza — 7% venta confirmada",
        "scope": "category",
        "category_slug": "manicura",
        "applies_to": "sale_confirmed",
        "rate_percent": 7.0,
        "priority": 200,
    },
    {
        "name": "Alquiler — 5% con mínimo 200.000 G.",
        "scope": "category",
        "category_slug": "alquiler-vehiculos",
        "applies_to": "sale_confirmed",
        "rate_percent": 5.0,
        "min_amount_pyg": 200_000,
        "priority": 200,
    },
    {
        "name": "Supermercado — 3% (margen fino)",
        "scope": "category",
        "category_slug": "supermercados-cadena",
        "applies_to": "sale_confirmed",
        "rate_percent": 3.0,
        "max_amount_per_event_pyg": 120_000,
        "priority": 200,
        "notes": "El margen de supermercado es fino: tope por evento para no romper la economía del socio.",
    },
    {
        "name": "Solicitud calificada — 25.000 G. fija",
        "scope": "global",
        "applies_to": "lead_accepted",
        "fixed_amount_pyg": 25_000,
        "priority": 800,
        "notes": "Solo aplicable si el contrato lo dice explícitamente (billing_model=cpl).",
    },
    {
        "name": "Almacén — 1% (prueba de margen negativo)",
        "scope": "company",
        "company_slug": "almacen-dona-nidia",
        "applies_to": "sale_confirmed",
        "rate_percent": 1.0,
        "priority": 100,
        "notes": "Caso de prueba: costos variables mayores a la comisión → debe marcarse como margen no positivo.",
    },
]

CONTRACTS: list[dict[str, Any]] = [
    {
        "number": "CTR-2026-001",
        "company_slug": "nails-mburucuya",
        "counterparty_name": "Mburucuyá Beauty E.I.R.L. (demo)",
        "contact_name": "Responsable del local",
        "billing_model": "rev_share",
        "rule_name": "Belleza — 7% venta confirmada",
        "attribution_window_days": 7,
        "cap_amount_pyg": 2_000_000,
        "cap_period": "month",
        "direct_costs_pyg": 4_000,
        "proof_requirements": {"kind": "manual_reconciliation", "fields": ["amount_pyg", "proof_ref"]},
        "partner_token": "prtds-socio-nails",
        "partner_name": "Encargada Nails Mburucuyá",
    },
    {
        "number": "CTR-2026-002",
        "company_slug": "rentcar-terere",
        "counterparty_name": "Tereré Movilidad S.A. (demo)",
        "contact_name": "Gerente de flota",
        "billing_model": "rev_share",
        "rule_name": "Alquiler — 5% con mínimo 200.000 G.",
        "attribution_window_days": 10,
        "direct_costs_pyg": 25_000,
        "proof_requirements": {"kind": "contract_or_confirmation", "fields": ["amount_pyg", "proof_ref"]},
        "partner_token": "prtds-socio-rentcar",
        "partner_name": "Gerente RentCar Tereré",
    },
    {
        "number": "CTR-2026-003",
        "company_slug": "supermercado-kaaguy",
        "counterparty_name": "Distribuidora Ka'aguy S.A. (demo)",
        "contact_name": "Jefa de marketing",
        "billing_model": "cpa",
        "rule_name": "Supermercado — 3% (margen fino)",
        "attribution_window_days": 5,
        "cap_amount_pyg": 3_000_000,
        "cap_period": "month",
        "direct_costs_pyg": 10_000,
        "proof_requirements": {"kind": "pos_report_or_manual", "fields": ["amount_pyg", "proof_ref"]},
        "partner_token": "prtds-socio-kaaguy",
        "partner_name": "Jefa de marketing Ka'aguy",
    },
    {
        "number": "CTR-2026-004",
        "company_slug": "almacen-dona-nidia",
        "counterparty_name": "Almacén Doña Nidia (demo)",
        "billing_model": "rev_share",
        "rule_name": "Almacén — 1% (prueba de margen negativo)",
        "direct_costs_pyg": 50_000,
        "proof_requirements": {"kind": "manual_reconciliation", "fields": ["amount_pyg"]},
        "partner_token": "prtds-socio-almacen",
        "partner_name": "Doña Nidia",
        "notes": "Contrato de prueba para verificar que el sistema marca margen de contribución no positivo.",
    },
    {
        "number": "CTR-2026-005",
        "company_slug": "tecnomovil-guarani",
        "counterparty_name": "TecnoMóvil Guaraní S.A. (demo)",
        "billing_model": "fixed_fee",
        "rule_name": "Global — 5% venta confirmada",
        "direct_costs_pyg": 20_000,
        "proof_requirements": {"kind": "partner_report", "fields": ["amount_pyg", "proof_ref"]},
        "partner_token": "prtds-socio-tecnomovil",
        "partner_name": "Gerente TecnoMóvil",
        "notes": "Posición promocional contratada: siempre etiquetada como publicidad en la búsqueda.",
    },
]

#: an operations account that can see every company (dev convenience)
OPS_PARTNER = {
    "full_name": "Operaciones PRTDS (demo)",
    "role": "owner",
    "scope": "all",
}
