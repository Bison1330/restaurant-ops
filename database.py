from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from flask_login import UserMixin

db = SQLAlchemy()

class Restaurant(db.Model):
    __tablename__ = 'restaurants'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    location = db.Column(db.String(200))
    gfs_account = db.Column(db.String(20))
    toast_location_id = db.Column(db.String(50))
    toast_client_id = db.Column(db.String(100))
    toast_client_secret = db.Column(db.String(200))
    last_toast_sync = db.Column(db.DateTime)
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
    # Manager-set override for cases where Toast has no wage data (e.g. salaried
    # staff or employees whose wageOverrides aren't populated). When set, this
    # value wins over the Toast-synced pay_rate in labor cost calculations.
    manual_pay_rate = db.Column(db.Float, nullable=True)
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


class Alert(db.Model):
    __tablename__ = 'alerts'
    id = db.Column(db.Integer, primary_key=True)
    restaurant_id = db.Column(db.Integer, db.ForeignKey('restaurants.id'), index=True)
    alert_type = db.Column(db.String(50))  # invoice_overdue, low_stock, zero_cost_recipe, unmapped_invoice_line, stale_toast_sync
    severity = db.Column(db.String(20))    # info, warning, critical
    message = db.Column(db.String(500))
    resolved = db.Column(db.Boolean, default=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    resolved_at = db.Column(db.DateTime)
    restaurant = db.relationship('Restaurant', backref='alerts')


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


class MenuItemSale(db.Model):
    """One row per menu item sold on a given day, aggregated from Toast PMIX."""
    __tablename__ = 'menu_item_sales'
    id = db.Column(db.Integer, primary_key=True)
    restaurant_id = db.Column(db.Integer, db.ForeignKey('restaurants.id'), index=True)
    sale_date = db.Column(db.DateTime, index=True)
    toast_item_guid = db.Column(db.String(100), index=True)
    item_name = db.Column(db.String(200))
    category = db.Column(db.String(100))
    quantity = db.Column(db.Integer, default=0)
    unit_price = db.Column(db.Float, default=0)
    total_revenue = db.Column(db.Float, default=0)
    recipe_id = db.Column(db.Integer, db.ForeignKey('recipes.id'), nullable=True)
    restaurant = db.relationship('Restaurant', backref='menu_item_sales')
    recipe = db.relationship('Recipe', backref='sales')

    @property
    def variance_percent(self):
        if self.expected_count and self.expected_count > 0:
            return (self.variance / self.expected_count) * 100
        return 0


class Shift(db.Model):
    """A scheduled or actual shift for one employee on one day."""
    __tablename__ = 'shifts'
    id = db.Column(db.Integer, primary_key=True)
    restaurant_id = db.Column(db.Integer, db.ForeignKey('restaurants.id'), index=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), index=True)
    shift_date = db.Column(db.Date, index=True, nullable=False)
    start_time = db.Column(db.String(5), nullable=False)
    end_time = db.Column(db.String(5), nullable=False)
    role = db.Column(db.String(50))
    status = db.Column(db.String(20), default='scheduled')
    notes = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    restaurant = db.relationship('Restaurant', backref='shifts')
    employee = db.relationship('Employee', backref='shifts')

    @property
    def hours(self):
        try:
            sh, sm = map(int, self.start_time.split(':'))
            eh, em = map(int, self.end_time.split(':'))
            start_mins = sh * 60 + sm
            end_mins = eh * 60 + em
            if end_mins <= start_mins:
                end_mins += 1440
            return (end_mins - start_mins) / 60
        except Exception:
            return 0

    @property
    def labor_cost(self):
        emp = self.employee
        if not emp:
            return 0
        rate = emp.manual_pay_rate if emp.manual_pay_rate is not None else emp.pay_rate
        if emp.pay_type == 'salary':
            return (rate / 52 / 5)
        return self.hours * (rate or 0)


class User(UserMixin, db.Model):
    """Login account for owners and managers."""
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False, index=True)
    email = db.Column(db.String(100), unique=True, nullable=True)
    password_hash = db.Column(db.String(200), nullable=False)
    first_name = db.Column(db.String(50))
    last_name = db.Column(db.String(50))
    role = db.Column(db.String(20), default='manager')  # owner | manager | employee
    restaurant_id = db.Column(db.Integer, db.ForeignKey('restaurants.id'), nullable=True)
    # NULL restaurant_id = access to all restaurants (owners)
    phone = db.Column(db.String(20))
    temp_password = db.Column(db.Boolean, default=True)  # force change on first login
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime, nullable=True)

    restaurant = db.relationship('Restaurant', backref='users')

    def set_password(self, password):
        from werkzeug.security import generate_password_hash
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        from werkzeug.security import check_password_hash
        return check_password_hash(self.password_hash, password)

    @property
    def full_name(self):
        return f"{self.first_name or ''} {self.last_name or ''}".strip() or self.username

    @property
    def is_owner(self):
        return self.role == 'owner'

    @property
    def is_manager(self):
        return self.role in ('owner', 'manager')

    def can_access_restaurant(self, restaurant_id):
        if self.role == 'owner':
            return True
        return self.restaurant_id == restaurant_id


class Position(db.Model):
    """A job position with a display color, per restaurant."""
    __tablename__ = 'positions'
    id = db.Column(db.Integer, primary_key=True)
    restaurant_id = db.Column(db.Integer, db.ForeignKey('restaurants.id'), index=True)
    name = db.Column(db.String(50), nullable=False)
    color_hex = db.Column(db.String(7), default='#64748b')  # e.g. #3b82f6
    display_order = db.Column(db.Integer, default=0)
    active = db.Column(db.Boolean, default=True)

    restaurant = db.relationship('Restaurant', backref='positions')

    @property
    def color_rgb(self):
        """Return r,g,b from hex for use in rgba() CSS."""
        h = self.color_hex.lstrip('#')
        return ','.join(str(int(h[i:i+2], 16)) for i in (0, 2, 4))


class RestaurantSettings(db.Model):
    """Per-restaurant configuration settings."""
    __tablename__ = 'restaurant_settings'
    id = db.Column(db.Integer, primary_key=True)
    restaurant_id = db.Column(db.Integer, db.ForeignKey('restaurants.id'), unique=True, index=True)
    week_start = db.Column(db.String(10), default='monday')
    overtime_weekly_enabled = db.Column(db.Boolean, default=True)
    overtime_weekly_hours = db.Column(db.Float, default=40.0)
    overtime_weekly_rate = db.Column(db.Float, default=1.5)
    overtime_daily_enabled = db.Column(db.Boolean, default=False)
    overtime_daily_hours = db.Column(db.Float, default=8.0)
    overtime_daily_rate = db.Column(db.Float, default=1.5)
    labor_pct_goal = db.Column(db.Float, default=25.0)
    clopening_warning = db.Column(db.Boolean, default=True)
    clopening_min_hours = db.Column(db.Float, default=10.0)
    shift_acceptance = db.Column(db.Boolean, default=False)
    allow_shift_swaps = db.Column(db.Boolean, default=True)
    unavailability_approval = db.Column(db.Boolean, default=True)
    pto_enabled = db.Column(db.Boolean, default=True)
    pto_requires_approval = db.Column(db.Boolean, default=True)
    pto_accrual_rate = db.Column(db.Float, default=0.025)
    pto_usage_cap = db.Column(db.Float, default=40.0)
    early_clockin_minutes = db.Column(db.Integer, default=5)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    restaurant = db.relationship('Restaurant', backref='settings_obj')


class ManagerPreference(db.Model):
    """Per-manager notification and display preferences."""
    __tablename__ = 'manager_preferences'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), unique=True, index=True)
    notify_pto_email = db.Column(db.Boolean, default=True)
    notify_pto_sms = db.Column(db.Boolean, default=True)
    notify_pto_inapp = db.Column(db.Boolean, default=True)
    notify_shift_email = db.Column(db.Boolean, default=False)
    notify_shift_sms = db.Column(db.Boolean, default=True)
    notify_shift_inapp = db.Column(db.Boolean, default=True)
    notify_low_stock_email = db.Column(db.Boolean, default=True)
    notify_low_stock_inapp = db.Column(db.Boolean, default=True)
    notify_payroll_email = db.Column(db.Boolean, default=True)
    notify_payroll_inapp = db.Column(db.Boolean, default=True)
    notify_invoice_email = db.Column(db.Boolean, default=False)
    notify_invoice_inapp = db.Column(db.Boolean, default=True)
    phone_number = db.Column(db.String(20))
    email_override = db.Column(db.String(100))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    user = db.relationship('User', backref='preferences')


class PTOPolicy(db.Model):
    """PTO accrual policy per restaurant."""
    __tablename__ = 'pto_policies'
    id = db.Column(db.Integer, primary_key=True)
    restaurant_id = db.Column(db.Integer, db.ForeignKey('restaurants.id'), unique=True, index=True)
    accrual_rate = db.Column(db.Float, default=0.025)       # hrs earned per hr worked (1/40)
    usage_cap = db.Column(db.Float, default=40.0)           # max hrs usable per calendar year
    balance_expires = db.Column(db.Boolean, default=False)  # IL law: never expires
    requires_approval = db.Column(db.Boolean, default=True)
    enabled = db.Column(db.Boolean, default=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)
    restaurant = db.relationship('Restaurant', backref='pto_policy')


class PTOBalance(db.Model):
    """Running PTO balance per employee per calendar year."""
    __tablename__ = 'pto_balances'
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), index=True)
    restaurant_id = db.Column(db.Integer, db.ForeignKey('restaurants.id'), index=True)
    year = db.Column(db.Integer, nullable=False)
    hours_accrued = db.Column(db.Float, default=0.0)   # total earned this year
    hours_used = db.Column(db.Float, default=0.0)      # total used this year
    hours_carried = db.Column(db.Float, default=0.0)   # carried over from last year
    last_accrual_date = db.Column(db.Date, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)

    employee = db.relationship('Employee', backref='pto_balances')
    restaurant = db.relationship('Restaurant', backref='pto_balances')

    @property
    def total_available(self):
        """Total hours available to use (accrued + carried, never negative)."""
        return max(0.0, self.hours_accrued + self.hours_carried - self.hours_used)

    @property
    def hours_remaining_this_year(self):
        """Remaining usage this year against the annual cap."""
        from sqlalchemy.orm import object_session
        policy = PTOPolicy.query.filter_by(restaurant_id=self.restaurant_id).first()
        cap = policy.usage_cap if policy else 40.0
        return max(0.0, cap - self.hours_used)


class PTORequest(db.Model):
    """A single PTO request from an employee."""
    __tablename__ = 'pto_requests'
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), index=True)
    restaurant_id = db.Column(db.Integer, db.ForeignKey('restaurants.id'), index=True)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    hours_requested = db.Column(db.Float, nullable=False)
    notes = db.Column(db.String(300))                   # optional — IL law, cannot require reason
    status = db.Column(db.String(20), default='pending') # pending|approved|denied
    denial_reason = db.Column(db.String(50))             # dropdown choice
    denial_notes = db.Column(db.String(300))             # manager notes on denial
    reviewed_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    payroll_run_id = db.Column(db.Integer, db.ForeignKey('payroll_runs.id'), nullable=True)
    requested_at = db.Column(db.DateTime, default=datetime.utcnow)

    employee = db.relationship('Employee', backref='pto_requests')
    restaurant = db.relationship('Restaurant', backref='pto_requests')
    reviewed_by = db.relationship('User', backref='pto_reviews')

    @property
    def days_requested(self):
        if self.start_date and self.end_date:
            return (self.end_date - self.start_date).days + 1
        return 0

    @property
    def date_range_display(self):
        if self.start_date == self.end_date:
            return self.start_date.strftime('%b %-d, %Y')
        return f"{self.start_date.strftime('%b %-d')} – {self.end_date.strftime('%b %-d, %Y')}"


class ScheduleWeek(db.Model):
    """Tracks draft/published state for a schedule week."""
    __tablename__ = 'schedule_weeks'
    id = db.Column(db.Integer, primary_key=True)
    restaurant_id = db.Column(db.Integer, db.ForeignKey('restaurants.id'), index=True)
    week_start = db.Column(db.Date, nullable=False, index=True)  # always Monday
    status = db.Column(db.String(20), default='draft')  # draft | published
    published_at = db.Column(db.DateTime, nullable=True)
    published_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    restaurant = db.relationship('Restaurant', backref='schedule_weeks')
    published_by = db.relationship('User', backref='published_schedules')

    __table_args__ = (
        db.UniqueConstraint('restaurant_id', 'week_start', name='uq_schedule_week'),
    )


class ShiftTemplate(db.Model):
    """A named collection of shifts that can be loaded onto any week."""
    __tablename__ = 'shift_templates'
    id = db.Column(db.Integer, primary_key=True)
    restaurant_id = db.Column(db.Integer, db.ForeignKey('restaurants.id'), index=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(200))
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    restaurant = db.relationship('Restaurant', backref='shift_templates')
    created_by = db.relationship('User', backref='shift_templates')


class ShiftTemplateEntry(db.Model):
    """One shift within a template. day_of_week: 0=Mon, 6=Sun."""
    __tablename__ = 'shift_template_entries'
    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(db.Integer, db.ForeignKey('shift_templates.id'), index=True)
    day_of_week = db.Column(db.Integer, nullable=False)  # 0=Mon, 6=Sun
    start_time = db.Column(db.String(5), nullable=False)
    end_time = db.Column(db.String(5), nullable=False)
    role = db.Column(db.String(50))
    notes = db.Column(db.String(200))
    # Optional: pin to a specific employee, or leave null for unassigned
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=True)
    template = db.relationship('ShiftTemplate', backref='entries')
    employee = db.relationship('Employee', backref='template_entries')


class OpenShift(db.Model):
    """An unassigned shift any eligible employee can claim."""
    __tablename__ = 'open_shifts'
    id = db.Column(db.Integer, primary_key=True)
    restaurant_id = db.Column(db.Integer, db.ForeignKey('restaurants.id'), index=True)
    shift_date = db.Column(db.Date, nullable=False, index=True)
    start_time = db.Column(db.String(5), nullable=False)
    end_time = db.Column(db.String(5), nullable=False)
    role = db.Column(db.String(50))
    notes = db.Column(db.String(200))
    status = db.Column(db.String(20), default='open')  # open | claimed | cancelled
    claimed_by_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=True)
    claimed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    restaurant = db.relationship('Restaurant', backref='open_shifts')
    claimed_by = db.relationship('Employee', backref='claimed_shifts')

    @property
    def hours(self):
        try:
            sh, sm = map(int, self.start_time.split(':'))
            eh, em = map(int, self.end_time.split(':'))
            start_mins = sh * 60 + sm
            end_mins = eh * 60 + em
            if end_mins <= start_mins:
                end_mins += 1440
            return (end_mins - start_mins) / 60
        except Exception:
            return 0


class ProjectedSales(db.Model):
    """Manager-entered projected sales for a specific date."""
    __tablename__ = 'projected_sales'
    id = db.Column(db.Integer, primary_key=True)
    restaurant_id = db.Column(db.Integer, db.ForeignKey('restaurants.id'), index=True)
    sale_date = db.Column(db.Date, nullable=False, index=True)
    projected_amount = db.Column(db.Float, default=0.0)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)
    restaurant = db.relationship('Restaurant', backref='projected_sales')

    __table_args__ = (
        db.UniqueConstraint('restaurant_id', 'sale_date', name='uq_projected_sales'),
    )


class EmployeeAvailability(db.Model):
    """Recurring weekly unavailability set by employee."""
    __tablename__ = 'employee_availability'
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), index=True)
    restaurant_id = db.Column(db.Integer, db.ForeignKey('restaurants.id'), index=True)
    day_of_week = db.Column(db.Integer, nullable=False)  # 0=Mon, 6=Sun
    all_day = db.Column(db.Boolean, default=True)
    start_time = db.Column(db.String(5), nullable=True)
    end_time = db.Column(db.String(5), nullable=True)
    reason = db.Column(db.String(200))
    status = db.Column(db.String(20), default='approved')  # pending | approved | denied
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    employee = db.relationship('Employee', backref='availability')
    restaurant = db.relationship('Restaurant', backref='employee_availability')


class ShiftPreset(db.Model):
    """A named time preset for a position (e.g. 'Bartender AM', 'Host PM').
    Used to auto-fill start/end times when creating a shift."""
    __tablename__ = 'shift_presets'
    id = db.Column(db.Integer, primary_key=True)
    restaurant_id = db.Column(db.Integer, db.ForeignKey('restaurants.id'), index=True)
    name = db.Column(db.String(100), nullable=False)
    position_name = db.Column(db.String(50))
    start_time = db.Column(db.String(5), nullable=False)
    end_time = db.Column(db.String(5), nullable=False)
    color_hex = db.Column(db.String(7), default='#64748b')
    display_order = db.Column(db.Integer, default=0)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    restaurant = db.relationship('Restaurant', backref='shift_presets')

    @property
    def hours(self):
        try:
            sh, sm = map(int, self.start_time.split(':'))
            eh, em = map(int, self.end_time.split(':'))
            start_mins = sh * 60 + sm
            end_mins = eh * 60 + em
            if end_mins <= start_mins:
                end_mins += 1440
            return (end_mins - start_mins) / 60
        except Exception:
            return 0


class EmployeeJob(db.Model):
    """One row per employee per job/position, with individual wage.
    Synced from Toast wageOverrides + jobReferences."""
    __tablename__ = 'employee_jobs'
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), index=True)
    restaurant_id = db.Column(db.Integer, db.ForeignKey('restaurants.id'), index=True)
    toast_job_guid = db.Column(db.String(100))
    job_name = db.Column(db.String(50), nullable=False)
    wage = db.Column(db.Float, default=0.0)
    is_primary = db.Column(db.Boolean, default=False)
    effective_date = db.Column(db.Date, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)
    employee = db.relationship('Employee', backref='jobs')
    restaurant = db.relationship('Restaurant', backref='employee_jobs')


class EmployeeProfile(db.Model):
    """Extended profile fields for an employee not stored in Toast."""
    __tablename__ = 'employee_profiles'
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), unique=True, index=True)
    preferred_name = db.Column(db.String(50))
    email = db.Column(db.String(100))
    phone = db.Column(db.String(20))
    date_of_birth = db.Column(db.Date, nullable=True)
    hire_date = db.Column(db.Date, nullable=True)
    preferred_hours_week = db.Column(db.Float, nullable=True)
    hide_from_schedule = db.Column(db.Boolean, default=False)
    notes = db.Column(db.Text)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)
    employee = db.relationship('Employee', backref=db.backref('profile', uselist=False))


class EmployeeDocument(db.Model):
    """Certification and document tracking per employee."""
    __tablename__ = 'employee_documents'
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), index=True)
    restaurant_id = db.Column(db.Integer, db.ForeignKey('restaurants.id'), index=True)
    document_type = db.Column(db.String(50), nullable=False)
    # Types: Food Handler | BASSET | CFPM | ServSafe | Allergen | I9 | W4 | Custom
    document_name = db.Column(db.String(200))
    file_path = db.Column(db.String(500), nullable=True)
    issued_date = db.Column(db.Date, nullable=True)
    expiration_date = db.Column(db.Date, nullable=True)
    notes = db.Column(db.String(300))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)
    employee = db.relationship('Employee', backref='documents')
    restaurant = db.relationship('Restaurant', backref='employee_documents')

    @property
    def status(self):
        if not self.expiration_date:
            return 'valid'
        from datetime import date, timedelta
        today = date.today()
        if self.expiration_date < today:
            return 'expired'
        elif self.expiration_date <= today + timedelta(days=30):
            return 'expiring_soon'
        return 'valid'

    @property
    def days_until_expiration(self):
        if not self.expiration_date:
            return None
        from datetime import date
        return (self.expiration_date - date.today()).days
