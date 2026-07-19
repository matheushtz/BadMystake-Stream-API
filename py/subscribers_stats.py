"""Calculo de estatisticas a partir da lista de subscribers da Twitch."""

TIER_KEYS = ("1000", "2000", "3000")


def compute_subscriber_stats(subscribers):
    tier_counts = {key: 0 for key in TIER_KEYS}
    gifted = 0
    gifters = set()

    for sub in subscribers:
        tier = str(sub.get("tier", "") or "")
        if tier in tier_counts:
            tier_counts[tier] += 1

        if sub.get("is_gift"):
            gifted += 1
            gifter_id = sub.get("gifter_id")
            if gifter_id:
                gifters.add(gifter_id)

    total = len(subscribers)

    return {
        "total": total,
        "tier1": tier_counts["1000"],
        "tier2": tier_counts["2000"],
        "tier3": tier_counts["3000"],
        "gifted": gifted,
        "regular": total - gifted,
        "unique_gifters": len(gifters),
    }
