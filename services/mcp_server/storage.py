from typing import List, Dict, Any

LOGS_DB: Dict[str, List[str]] = {
    "1800003902272": [
        '2025-09-02 02:37:54.156 [http-nio-8080-exec-13] INFO '
        'r.r.s.o.c.c.LoggingFilter: '
        'Request POST /orders/close: <request orderId="1800003902272" '
        'orderStatus="ORDER_STATUS_DENIED" '
        'orderStatusDateTime="2025-09-02T05:37:53+03:00" '
        'orderStatusExt="44" reqType="SET_ORDER_STATUS"/>',
    ],
    "1800003879400": [
        '2025-09-10 11:10:10.010 INFO some.logger: Request POST '
        '/orders/close: <request orderId="1800003879400" orderStatus="OK"/>',
    ],
}

# СУЛЗ (mock)
ORDERS_DB: Dict[str, Dict[str, Any]] = {
    "1800003902272": {"status": "DENIED", "comment": "Initial mock status"},
    "1800003879400": {"status": "DENIED", "comment": "Initial mock status"},
}

# EISSD (mock)
EISSD_DB: Dict[str, Dict[str, Any]] = {
    "1800003902272": {"status": "IN_PROGRESS"},
    "1800003879400": {"status": "IN_PROGRESS"},
}

# OTRS (mock)
OTRS_COMMENTS: List[Dict[str, Any]] = []
OTRS_TICKETS: Dict[str, Dict[str, Any]] = {
}
