from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class Restaurant(db.Model):
    __tablename__ = 'restaurants'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    location = db.Column(db.String(200))
    gfs_account = db.Column(db.String(20))
    toast_location_id = db.Column(db.String(50))
    active = db.Column(db.Boolean, default=True)

class Vendor(db.Model):
    __tablename__ = 'vendors'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    type = db.Column(db.String(50))
    account_number = db.Column(db.String(50))
    contact_email = db.Column(db.String(100))
    payment_terms = db.Column(db.Integer, default=30)
    active = db.Column(db.Boolean, default=True)

class InventoryItem(db.Model):
    __tablename__ = 'inventory_items'
    id = db.Column(db.Integer, primary_key=True)
    restaurant_id = db.Column(db.Integer, db.ForeignKey('restaurants.id'))
    name = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(50))
    unit = db.Column(db.String(30))
    par_level = db.Column(db.Float, default=0)
    current_stock = db.Column(db.Float, default=0)
    last_cost = db.Column(db.Float, default=0)  # cost per purchase unit (case, bag, etc.)
    yield_units = db.Column(db.Float, default=1)  # how many recipe units per purchase unit (e.g. 640 oz per 40lb case)
    vendor_id = db.Column(db.Integer, db.ForeignKey('vendors.id'))
    vendor_sku = db.Column(db.String(50))
    toast_guid = db.Column(db.String(100))
    gfs_sku = db.Column(db.String(50))
    fintech_code = db.Column(db.String(50))
    xtra_chef_id = db.Column(db.String(100))
    restaurant = db.relationship('Restaurant', backref='inventory_items')
    vendor = db.relationship('Vendor', backref='inventory_items')

class Invoice(db.Model):
    __tablename__ = 'invoices'
    id = db.Column(db.Integer, primary_key=True)
    restaurant_id = db.Column(db.Integer, db.ForeignKey('restaurants.id'))
    vendor_id = db.Column(db.Integer, db.ForeignKey('vendors.id'))
    invoice_number = db.Column(db.String(50))
    invoice_date = db.Column(db.Date)
    due_date = db.Column(db.Date)
    total_amount = db.Column(db.Float, default=0)
    status = db.Column(db.String(20), default='pending')
    source = db.Column(db.String(50))
    imported_at = db.Column(db.DateTime, default=datetime.utcnow)
    approved_at = db.Column(db.DateTime)
    paid_at = db.Column(db.DateTime)
    qb_exported = db.Column(db.Boolean, default=False)
    restaurant = db.relationship('Restaurant', backref='invoices')
    vendor = db.relationship('Vendor', backref='invoices')

class InvoiceLine(db.Model):
    __tablename__ = 'invoice_lines'
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoices.id'))
    description = db.Column(db.String(200))
    vendor_sku = db.Column(db.String(50))
    quantity = db.Column(db.Float, default=0)
    unit = db.Column(db.String(30))
    unit_cost = db.Column(db.Float, default=0)
    line_total = db.Column(db.Float, default=0)
    inventory_item_id = db.Column(db.Integer, db.ForeignKey('inventory_items.id'), nullable=True)
    invoice = db.relationship('Invoice', backref='lines')
    inventory_item = db.relationship('InventoryItem', backref='invoice_lines')

class PayrollRun(db.Model):
    __tablename__ = 'payroll_runs'
    id = db.Column(db.Integer, primary_key=True)
    restaurant_id = db.Column(db.Integer, db.ForeignKey('restaurants.id'))
    period_start = db.Column(db.Date)
    period_end = db.Column(db.Date)
    status = db.Column(db.String(20), default='draft')
    total_gross = db.Column(db.Float, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    qb_exported = db.Column(db.Boolean, default=False)
    restaurant = db.relationship('Restaurant', backref='payroll_runs')

class Employee(db.Model):
    __tablename__ = 'employees'
    id = db.Column(db.Integer, primary_key=True)
    restaurant_id = db.Column(db.Integer, db.ForeignKey('restaurants.id'))
    toast_employee_id = db.Column(db.String(50))
    first_name = db.Column(db.String(50))
    last_name = db.Column(db.String(50))
    role = db.Column(db.String(50))
    pay_rate = db.Column(db.Float, default=0)
    pay_type = db.Column(db.String(20))
    filing_status = db.Column(db.String(20))
    allowances = db.Column(db.Integer, default=0)
    active = db.Column(db.Boolean, default=True)
    restaurant = db.relationship('Restaurant', backref='employees')

class Recipe(db.Model):
    __tablename__ = 'recipes'
    id = db.Column(db.Integer, primary_key=True)
    restaurant_id = db.Column(db.Integer, db.ForeignKey('restaurants.id'))
    name = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(20))  # food or beverage
    subcategory = db.Column(db.String(100))  # appetizer, entree, cocktail, beer, wine, etc.
    menu_price = db.Column(db.Float, default=0)
    food_cost = db.Column(db.Float, default=0)
    food_cost_pct = db.Column(db.Float, default=0)
    gross_margin = db.Column(db.Float, default=0)
    portion_size = db.Column(db.String(50))
    toast_recipe_id = db.Column(db.String(50))
    xtra_chef_id = db.Column(db.String(50))
    toast_guid = db.Column(db.String(100))
    pos_id = db.Column(db.String(100))
    notes = db.Column(db.Text)
    status = db.Column(db.String(20), default='active')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    restaurant = db.relationship('Restaurant', backref='recipes')
    ingredients = db.relationship('RecipeIngredient', backref='recipe', cascade='all, delete-orphan')

    @property
    def total_cost(self):
        return sum(ing.cost for ing in self.ingredients)

    @property
    def margin(self):
        if self.menu_price and self.menu_price > 0:
            return self.menu_price - self.total_cost
        return 0

    @property
    def margin_percent(self):
        if self.menu_price and self.menu_price > 0:
            return ((self.menu_price - self.total_cost) / self.menu_price) * 100
        return 0

    @property
    def cost_percent(self):
        if self.menu_price and self.menu_price > 0:
            return (self.total_cost / self.menu_price) * 100
        return 0

class RecipeIngredient(db.Model):
    __tablename__ = 'recipe_ingredients'
    id = db.Column(db.Integer, primary_key=True)
    recipe_id = db.Column(db.Integer, db.ForeignKey('recipes.id'))
    inventory_item_id = db.Column(db.Integer, db.ForeignKey('inventory_items.id'), nullable=True)
    name = db.Column(db.String(200))
    quantity = db.Column(db.Float, default=0)
    unit = db.Column(db.String(30))
    unit_cost = db.Column(db.Float, default=0)  # fallback cost when no inventory link
    yield_percent = db.Column(db.Float, default=100)
    inventory_item = db.relationship('InventoryItem', backref='recipe_ingredients')

    @property
    def effective_unit_cost(self):
        """Use live inventory pricing when linked, fall back to static unit_cost."""
        if self.inventory_item and self.inventory_item.last_cost > 0:
            # Convert from bulk cost to per-unit cost using yield_units if set
            return self.inventory_item.last_cost / (self.inventory_item.yield_units or 1)
        return self.unit_cost

    @property
    def cost(self):
        return self.quantity * self.effective_unit_cost


class ItemAlias(db.Model):
    __tablename__ = 'item_aliases'
    id = db.Column(db.Integer, primary_key=True)
    inventory_item_id = db.Column(db.Integer, db.ForeignKey('inventory_items.id'))
    source = db.Column(db.String(30))  # gfs, fintech, toast, ocr, xtra_chef, manual
    external_sku = db.Column(db.String(100))  # vendor SKU or external ID
    external_name = db.Column(db.String(300))  # description as it appears in external system
    confidence = db.Column(db.Float, default=1.0)  # 1.0 = confirmed, <1.0 = auto-matched
    confirmed = db.Column(db.Boolean, default=False)  # user-verified match
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    inventory_item = db.relationship('InventoryItem', backref='aliases')


class PriceHistory(db.Model):
    __tablename__ = 'price_history'
    id = db.Column(db.Integer, primary_key=True)
    inventory_item_id = db.Column(db.Integer, db.ForeignKey('inventory_items.id'))
    old_cost = db.Column(db.Float)
    new_cost = db.Column(db.Float)
    change_percent = db.Column(db.Float)
    source = db.Column(db.String(30))  # gfs, fintech, ocr, manual
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoices.id'), nullable=True)
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow)
    inventory_item = db.relationship('InventoryItem', backref='price_history')
    invoice = db.relationship('Invoice', backref='price_updates')


class UnmatchedItem(db.Model):
    __tablename__ = 'unmatched_items'
    id = db.Column(db.Integer, primary_key=True)
    restaurant_id = db.Column(db.Integer, db.ForeignKey('restaurants.id'))
    source = db.Column(db.String(30))  # gfs, fintech, ocr, toast, xtra_chef
    external_sku = db.Column(db.String(100))
    external_name = db.Column(db.String(300))
    unit = db.Column(db.String(30))
    last_seen_cost = db.Column(db.Float, default=0)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoices.id'), nullable=True)
    suggested_item_id = db.Column(db.Integer, db.ForeignKey('inventory_items.id'), nullable=True)
    suggested_confidence = db.Column(db.Float, default=0)
    status = db.Column(db.String(20), default='pending')  # pending, matched, new_item, dismissed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    resolved_at = db.Column(db.DateTime)
    restaurant = db.relationship('Restaurant', backref='unmatched_items')
    suggested_item = db.relationship('InventoryItem', backref='suggested_matches')
    invoice = db.relationship('Invoice', backref='unmatched_items')


class StorageZone(db.Model):
    __tablename__ = 'storage_zones'
    id = db.Column(db.Integer, primary_key=True)
    restaurant_id = db.Column(db.Integer, db.ForeignKey('restaurants.id'))
    name = db.Column(db.String(100), nullable=False)
    sort_order = db.Column(db.Integer, default=0)
    active = db.Column(db.Boolean, default=True)
    restaurant = db.relationship('Restaurant', backref='storage_zones')


class InventoryItemZone(db.Model):
    """Maps inventory items to their storage zone(s) for count sheets."""
    __tablename__ = 'inventory_item_zones'
    id = db.Column(db.Integer, primary_key=True)
    inventory_item_id = db.Column(db.Integer, db.ForeignKey('inventory_items.id'))
    storage_zone_id = db.Column(db.Integer, db.ForeignKey('storage_zones.id'))
    sort_order = db.Column(db.Integer, default=0)
    inventory_item = db.relationship('InventoryItem', backref='zone_assignments')
    storage_zone = db.relationship('StorageZone', backref='item_assignments')


class CountSession(db.Model):
    __tablename__ = 'count_sessions'
    id = db.Column(db.Integer, primary_key=True)
    restaurant_id = db.Column(db.Integer, db.ForeignKey('restaurants.id'))
    count_date = db.Column(db.Date, nullable=False)
    counted_by = db.Column(db.String(100))
    status = db.Column(db.String(20), default='in_progress')  # in_progress, submitted, reviewed
    notes = db.Column(db.Text)
    total_value = db.Column(db.Float, default=0)
    total_variance_value = db.Column(db.Float, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    submitted_at = db.Column(db.DateTime)
    restaurant = db.relationship('Restaurant', backref='count_sessions')
    entries = db.relationship('CountEntry', backref='session', cascade='all, delete-orphan')


class ItemMap(db.Model):
    """Universal cross-system ID map for inventory items / recipe components."""
    __tablename__ = 'item_maps'
    id = db.Column(db.Integer, primary_key=True)
    internal_name = db.Column(db.String(200))
    toast_guid = db.Column(db.String(100), index=True)
    xtra_chef_id = db.Column(db.String(100), index=True)
    gfs_sku = db.Column(db.String(50), index=True)
    fintech_code = db.Column(db.String(50), index=True)
    category = db.Column(db.String(50))
    restaurant_id = db.Column(db.Integer, db.ForeignKey('restaurants.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    notes = db.Column(db.String(300))
    restaurant = db.relationship('Restaurant', backref='item_maps')


class CountEntry(db.Model):
    __tablename__ = 'count_entries'
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('count_sessions.id'))
    inventory_item_id = db.Column(db.Integer, db.ForeignKey('inventory_items.id'))
    storage_zone_id = db.Column(db.Integer, db.ForeignKey('storage_zones.id'), nullable=True)
    actual_count = db.Column(db.Float, default=0)
    expected_count = db.Column(db.Float, default=0)
    unit_cost = db.Column(db.Float, default=0)  # cost at time of count
    notes = db.Column(db.String(200))
    inventory_item = db.relationship('InventoryItem', backref='count_entries')
    storage_zone = db.relationship('StorageZone')

    @property
    def variance(self):
        return self.actual_count - self.expected_count

    @property
    def variance_value(self):
        return self.variance * self.unit_cost

    @property
    def variance_percent(self):
        if self.expected_count and self.expected_count > 0:
            return (self.variance / self.expected_count) * 100
        return 0
