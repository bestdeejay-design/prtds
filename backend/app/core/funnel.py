"""The funnel event dictionary — the single source of truth about *what an
event proves and what it does not prove*.

This mirrors concept §07 ("Обязательные события воронки") and §15 ("То, что
нельзя перепутать"). It is exposed through ``GET /api/meta/funnel`` so the UI,
the partner cabinet and any future BI report all use the same wording instead of
inventing their own interpretation.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class EventType(str, Enum):
    # awareness
    SEARCH_RESULT = "search_result"
    VIEW = "view"
    # interest
    CARD_OPEN = "card_open"
    ROUTE_CLICK = "route_click"
    SITE_CLICK = "site_click"
    # contact attempt
    WHATSAPP_CLICK = "whatsapp_click"
    CALL_CLICK = "call_click"
    # delivered / accepted request
    LEAD_SUBMITTED = "lead_submitted"
    LEAD_ACCEPTED = "lead_accepted"
    LEAD_REJECTED = "lead_rejected"
    LEAD_CANCELLED = "lead_cancelled"
    BOOKING_CONFIRMED = "booking_confirmed"
    VISIT_DONE = "visit_done"
    # money with proof
    SALE_CONFIRMED = "sale_confirmed"
    RECEIPT_MATCHED = "receipt_matched"
    # repeat
    REPEAT_PURCHASE = "repeat_purchase"
    # platform-side
    SETTLEMENT_CREATED = "settlement_created"


@dataclass(frozen=True, slots=True)
class EventSpec:
    code: EventType
    stage: str
    proves: str
    does_not_prove: str
    #: only these event types may create a commission basis
    commissionable: bool = False
    #: requires an explicit consent record before it may carry contact data
    requires_consent: bool = False


# Wording is kept in Spanish because it is shown to partners in Paraguay;
# the Russian equivalent lives in docs/architecture.md for the dev team.
FUNNEL: dict[EventType, EventSpec] = {
    EventType.SEARCH_RESULT: EventSpec(
        EventType.SEARCH_RESULT,
        "awareness",
        "Mostrado en los resultados de búsqueda.",
        "Que la persona esté interesada o haya comprado.",
    ),
    EventType.VIEW: EventSpec(
        EventType.VIEW,
        "awareness",
        "Impresión de una tarjeta en un listado.",
        "Interés real, lead o venta.",
    ),
    EventType.CARD_OPEN: EventSpec(
        EventType.CARD_OPEN,
        "interest",
        "Interés en la empresa (ficha abierta).",
        "Un lead calificado.",
    ),
    EventType.ROUTE_CLICK: EventSpec(
        EventType.ROUTE_CLICK,
        "interest",
        "Intención de llegar al local.",
        "Una visita efectivamente realizada.",
    ),
    EventType.SITE_CLICK: EventSpec(
        EventType.SITE_CLICK,
        "interest",
        "Salida hacia el sitio del vendedor.",
        "Una compra en ese sitio.",
    ),
    EventType.WHATSAPP_CLICK: EventSpec(
        EventType.WHATSAPP_CLICK,
        "contact",
        "Intento de iniciar contacto por WhatsApp.",
        "Mensaje recibido o conversación sostenida.",
    ),
    EventType.CALL_CLICK: EventSpec(
        EventType.CALL_CLICK,
        "contact",
        "Intento de iniciar contacto por llamada.",
        "Llamada efectivamente atendida.",
    ),
    EventType.LEAD_SUBMITTED: EventSpec(
        EventType.LEAD_SUBMITTED,
        "lead",
        "Solicitud entregada a PRTDS.",
        "Solicitud aceptada, visita u pago.",
        requires_consent=True,
    ),
    EventType.LEAD_ACCEPTED: EventSpec(
        EventType.LEAD_ACCEPTED,
        "lead",
        "Aceptación / confirmación por parte del vendedor.",
        "Dinero recibido por el vendedor.",
    ),
    EventType.LEAD_REJECTED: EventSpec(
        EventType.LEAD_REJECTED,
        "lead",
        "Rechazo documentado del vendedor.",
        "Que la solicitud no existiera.",
    ),
    EventType.LEAD_CANCELLED: EventSpec(
        EventType.LEAD_CANCELLED,
        "lead",
        "Cancelación documentada (cliente o vendedor).",
        "Que la solicitud no existiera o no fuera atendida.",
    ),
    EventType.BOOKING_CONFIRMED: EventSpec(
        EventType.BOOKING_CONFIRMED,
        "lead",
        "Turno/reserva confirmada por el proveedor.",
        "Pago realizado.",
    ),
    EventType.VISIT_DONE: EventSpec(
        EventType.VISIT_DONE,
        "lead",
        "Visita/servicio marcado como realizado por el proveedor.",
        "El importe cobrado.",
    ),
    EventType.SALE_CONFIRMED: EventSpec(
        EventType.SALE_CONFIRMED,
        "sale",
        "Venta con evidencia aportada por el vendedor.",
        "Derecho automático a comisión sin contrato.",
        commissionable=True,
    ),
    EventType.RECEIPT_MATCHED: EventSpec(
        EventType.RECEIPT_MATCHED,
        "sale",
        "Venta conciliada contra un comprobante.",
        "Derecho automático a comisión sin contrato.",
        commissionable=True,
    ),
    EventType.REPEAT_PURCHASE: EventSpec(
        EventType.REPEAT_PURCHASE,
        "retention",
        "Compra repetida dentro de los consentimientos otorgados.",
        "Causalidad de una campaña sin verificación.",
        commissionable=True,
    ),
    EventType.SETTLEMENT_CREATED: EventSpec(
        EventType.SETTLEMENT_CREATED,
        "settlement",
        "Cálculo de comisión registrado en el ledger.",
        "Dinero efectivamente cobrado por PRTDS.",
    ),
}

#: funnel order used by dashboards
STAGES = ("awareness", "interest", "contact", "lead", "sale", "retention", "settlement")

STAGE_LABELS_ES = {
    "awareness": "Visibilidad",
    "interest": "Interés",
    "contact": "Contacto",
    "lead": "Solicitud",
    "sale": "Venta",
    "retention": "Recompra",
    "settlement": "Liquidación",
}

#: things that must never be confused (concept §15)
NOT_EQUIVALENT_ES = (
    "Personas jurídicas en la base ≠ empresas publicadas y operativas.",
    "Impresión/clic/WhatsApp abierto ≠ cliente traído, y mucho menos venta confirmada.",
    "GMV de la tienda ≠ ingreso de PRTDS; los puntos/bonos ≠ dinero en cuenta.",
    "Migración, modelo o test en verde ≠ servicio de producción listo para vender.",
    "Respuesta de IA ≠ stock verificado, turno confirmado o descuento jurídicamente exacto.",
    "Crecimiento de tráfico ≠ modelo de negocio viable.",
)


def as_payload() -> dict:
    """Serialisable dictionary for ``GET /api/meta/funnel``."""
    return {
        "stages": [{"code": s, "label_es": STAGE_LABELS_ES[s]} for s in STAGES],
        "events": [
            {
                "code": spec.code.value,
                "stage": spec.stage,
                "proves_es": spec.proves,
                "does_not_prove_es": spec.does_not_prove,
                "commissionable": spec.commissionable,
                "requires_consent": spec.requires_consent,
            }
            for spec in FUNNEL.values()
        ],
        "not_equivalent_es": list(NOT_EQUIVALENT_ES),
    }
