"""
Central item matching engine.

Matches incoming invoice lines, recipe ingredients, and Toast items
to inventory items using a tiered strategy:
  1. Exact vendor_sku match on InventoryItem
  2. Alias lookup (previously confirmed matches)
  3. Fuzzy name matching with confidence scoring

When no match is found, creates an UnmatchedItem for manual review
and optionally suggests the best candidate.
"""

from difflib import SequenceMatcher
from datetime import datetime

from database import db, InventoryItem, ItemAlias, PriceHistory, UnmatchedItem


def match_item(restaurant_id, sku=None, name=None, source=None, unit=None,
               cost=None, invoice_id=None, auto_create_unmatched=True):
    """
    Try to match an incoming item to inventory. Returns dict:
        {
            "item": InventoryItem or None,
            "confidence": float 0-1,
            "match_type": "exact_sku" | "alias" | "fuzzy" | "none",
        }
    """
    # Tier 1: Exact vendor_sku match
    if sku:
        item = InventoryItem.query.filter_by(
            restaurant_id=restaurant_id, vendor_sku=sku
        ).first()
        if item:
            return {"item": item, "confidence": 1.0, "match_type": "exact_sku"}

    # Tier 2: Alias lookup (SKU-based, then name-based)
    if sku:
        alias = ItemAlias.query.filter_by(external_sku=sku).join(InventoryItem).filter(
            InventoryItem.restaurant_id == restaurant_id
        ).first()
        if alias:
            return {"item": alias.inventory_item, "confidence": alias.confidence, "match_type": "alias"}

    if name:
        alias = ItemAlias.query.filter_by(external_name=name).join(InventoryItem).filter(
            InventoryItem.restaurant_id == restaurant_id
        ).first()
        if alias:
            return {"item": alias.inventory_item, "confidence": alias.confidence, "match_type": "alias"}

    # Tier 3: Fuzzy name matching
    if name:
        best_match, best_score = _fuzzy_match(restaurant_id, name)
        if best_match and best_score >= 0.75:
            # High confidence — auto-match but mark as unconfirmed alias
            _save_alias(best_match.id, source, sku, name, confidence=best_score, confirmed=False)
            return {"item": best_match, "confidence": best_score, "match_type": "fuzzy"}

        # Low confidence — create unmatched item for review
        if auto_create_unmatched:
            _create_unmatched(
                restaurant_id=restaurant_id,
                source=source,
                sku=sku,
                name=name,
                unit=unit,
                cost=cost,
                invoice_id=invoice_id,
                suggested_item=best_match,
                suggested_confidence=best_score or 0,
            )
        return {"item": None, "confidence": best_score or 0, "match_type": "none"}

    return {"item": None, "confidence": 0, "match_type": "none"}


def confirm_match(unmatched_id, inventory_item_id):
    """User confirms a match — save alias, update unmatched status, link pricing."""
    unmatched = UnmatchedItem.query.get(unmatched_id)
    if not unmatched:
        return False

    item = InventoryItem.query.get(inventory_item_id)
    if not item:
        return False

    # Save confirmed alias
    _save_alias(
        inventory_item_id=item.id,
        source=unmatched.source,
        sku=unmatched.external_sku,
        name=unmatched.external_name,
        confidence=1.0,
        confirmed=True,
    )

    # Update pricing if we have cost data
    if unmatched.last_seen_cost and unmatched.last_seen_cost > 0:
        update_price(item, unmatched.last_seen_cost, unmatched.source, unmatched.invoice_id)

    # Mark resolved
    unmatched.status = "matched"
    unmatched.suggested_item_id = item.id
    unmatched.suggested_confidence = 1.0
    unmatched.resolved_at = datetime.utcnow()
    db.session.commit()
    return True


def create_new_from_unmatched(unmatched_id, category=None):
    """Create a new inventory item from an unmatched item."""
    unmatched = UnmatchedItem.query.get(unmatched_id)
    if not unmatched:
        return None

    item = InventoryItem(
        restaurant_id=unmatched.restaurant_id,
        name=unmatched.external_name,
        category=category or "uncategorized",
        unit=unmatched.unit or "each",
        last_cost=unmatched.last_seen_cost or 0,
        vendor_sku=unmatched.external_sku or "",
    )
    db.session.add(item)
    db.session.flush()

    # Save alias so future imports auto-match
    _save_alias(
        inventory_item_id=item.id,
        source=unmatched.source,
        sku=unmatched.external_sku,
        name=unmatched.external_name,
        confidence=1.0,
        confirmed=True,
    )

    unmatched.status = "new_item"
    unmatched.suggested_item_id = item.id
    unmatched.suggested_confidence = 1.0
    unmatched.resolved_at = datetime.utcnow()
    db.session.commit()
    return item


def dismiss_unmatched(unmatched_id):
    """Dismiss an unmatched item (not relevant, one-off, etc.)."""
    unmatched = UnmatchedItem.query.get(unmatched_id)
    if not unmatched:
        return False
    unmatched.status = "dismissed"
    unmatched.resolved_at = datetime.utcnow()
    db.session.commit()
    return True


def update_price(item, new_cost, source, invoice_id=None):
    """Update inventory item cost and log the change."""
    old_cost = item.last_cost or 0
    if new_cost == old_cost:
        return

    change_pct = ((new_cost - old_cost) / old_cost * 100) if old_cost > 0 else 0

    history = PriceHistory(
        inventory_item_id=item.id,
        old_cost=old_cost,
        new_cost=new_cost,
        change_percent=round(change_pct, 2),
        source=source,
        invoice_id=invoice_id,
    )
    db.session.add(history)
    item.last_cost = new_cost


def get_pending_unmatched(restaurant_id=None):
    """Get all pending unmatched items, optionally filtered by restaurant."""
    query = UnmatchedItem.query.filter_by(status="pending")
    if restaurant_id:
        query = query.filter_by(restaurant_id=restaurant_id)
    return query.order_by(UnmatchedItem.created_at.desc()).all()


def get_suggestions_for_unmatched(unmatched):
    """Get top 5 inventory item suggestions for an unmatched item."""
    items = InventoryItem.query.filter_by(restaurant_id=unmatched.restaurant_id).all()
    scored = []
    for item in items:
        score = _name_similarity(unmatched.external_name or "", item.name)
        if unmatched.external_sku and item.vendor_sku:
            sku_score = _name_similarity(unmatched.external_sku, item.vendor_sku)
            score = max(score, sku_score)
        if score > 0.3:
            scored.append((item, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:5]


def auto_link_recipe_ingredients(restaurant_id):
    """Re-link all unlinked recipe ingredients using the matcher."""
    from database import RecipeIngredient, Recipe
    unlinked = (
        RecipeIngredient.query
        .join(Recipe)
        .filter(
            Recipe.restaurant_id == restaurant_id,
            RecipeIngredient.inventory_item_id.is_(None),
        )
        .all()
    )
    linked_count = 0
    for ing in unlinked:
        result = match_item(
            restaurant_id=restaurant_id,
            name=ing.name,
            source="xtra_chef",
            auto_create_unmatched=False,
        )
        if result["item"] and result["confidence"] >= 0.7:
            ing.inventory_item_id = result["item"].id
            linked_count += 1
    db.session.commit()
    return linked_count


# --- Internal helpers ---

def _fuzzy_match(restaurant_id, name):
    """Find best fuzzy match among inventory items."""
    items = InventoryItem.query.filter_by(restaurant_id=restaurant_id).all()
    best_item = None
    best_score = 0

    name_lower = (name or "").lower().strip()
    # Extract key tokens for comparison
    name_tokens = set(name_lower.split())

    for item in items:
        item_lower = item.name.lower().strip()

        # SequenceMatcher ratio
        ratio = SequenceMatcher(None, name_lower, item_lower).ratio()

        # Token overlap bonus
        item_tokens = set(item_lower.split())
        common = name_tokens & item_tokens
        if name_tokens and item_tokens:
            token_score = len(common) / max(len(name_tokens), len(item_tokens))
        else:
            token_score = 0

        # Weighted score
        score = (ratio * 0.6) + (token_score * 0.4)

        if score > best_score:
            best_score = score
            best_item = item

    return best_item, best_score


def _name_similarity(a, b):
    """Simple similarity score between two strings."""
    if not a or not b:
        return 0
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def _save_alias(inventory_item_id, source, sku, name, confidence=1.0, confirmed=False):
    """Save an alias, avoiding duplicates."""
    existing = ItemAlias.query.filter_by(
        inventory_item_id=inventory_item_id,
        source=source,
        external_sku=sku or "",
        external_name=name or "",
    ).first()
    if existing:
        existing.confidence = max(existing.confidence, confidence)
        existing.confirmed = existing.confirmed or confirmed
        return existing

    alias = ItemAlias(
        inventory_item_id=inventory_item_id,
        source=source or "",
        external_sku=sku or "",
        external_name=name or "",
        confidence=confidence,
        confirmed=confirmed,
    )
    db.session.add(alias)
    return alias


def _create_unmatched(restaurant_id, source, sku, name, unit, cost,
                      invoice_id, suggested_item, suggested_confidence):
    """Create an unmatched item entry, avoiding duplicates for same sku+source."""
    if sku:
        existing = UnmatchedItem.query.filter_by(
            restaurant_id=restaurant_id,
            source=source,
            external_sku=sku,
            status="pending",
        ).first()
        if existing:
            existing.last_seen_cost = cost or existing.last_seen_cost
            return existing

    unmatched = UnmatchedItem(
        restaurant_id=restaurant_id,
        source=source or "",
        external_sku=sku or "",
        external_name=name or "",
        unit=unit or "",
        last_seen_cost=cost or 0,
        invoice_id=invoice_id,
        suggested_item_id=suggested_item.id if suggested_item else None,
        suggested_confidence=suggested_confidence,
    )
    db.session.add(unmatched)
    return unmatched
