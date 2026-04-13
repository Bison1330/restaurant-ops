#!/usr/bin/env python3
"""
Seed inventory items, storage zones, and count sheets from xtraCHEF data.
Run with: python seed_inventory.py
Safe to re-run — uses upsert logic, won't duplicate.
"""
import sys
sys.path.insert(0, '/root/restaurant-ops')

from app import app
from database import db, Restaurant, InventoryItem, StorageZone, CountSheet, InventoryItemZone

def get_or_create_zone(restaurant_id, name, count_day=None, count_time=None, sort_order=0):
    zone = StorageZone.query.filter_by(restaurant_id=restaurant_id, name=name).first()
    if not zone:
        zone = StorageZone(
            restaurant_id=restaurant_id,
            name=name,
            count_day=count_day,
            count_time=count_time,
            sort_order=sort_order,
            active=True,
        )
        db.session.add(zone)
        db.session.flush()
    return zone

def get_or_create_sheet(restaurant_id, zone_id, name, item_count=0, sort_order=0):
    sheet = CountSheet.query.filter_by(restaurant_id=restaurant_id, storage_zone_id=zone_id).first()
    if not sheet:
        sheet = CountSheet(
            restaurant_id=restaurant_id,
            storage_zone_id=zone_id,
            name=name,
            status='published',
            item_count=item_count,
            sort_order=sort_order,
        )
        db.session.add(sheet)
        db.session.flush()
    return sheet

def add_item(restaurant_id, name, category, unit, zone_name=None):
    item = InventoryItem.query.filter_by(restaurant_id=restaurant_id, name=name).first()
    if not item:
        item = InventoryItem(
            restaurant_id=restaurant_id,
            name=name, category=category, unit=unit,
            vendor_sku='', par_level=0, current_stock=0, last_cost=0,
        )
        db.session.add(item)
        db.session.flush()
    if zone_name:
        zone = StorageZone.query.filter_by(restaurant_id=restaurant_id, name=zone_name).first()
        if zone:
            exists = InventoryItemZone.query.filter_by(
                inventory_item_id=item.id, storage_zone_id=zone.id
            ).first()
            if not exists:
                db.session.add(InventoryItemZone(
                    inventory_item_id=item.id, storage_zone_id=zone.id, sort_order=0))
    return item

if __name__ == '__main__':
    with app.app_context():
        hale = Restaurant.query.filter(Restaurant.name.ilike('%hale%')).first()
        jackson = Restaurant.query.filter(Restaurant.name.ilike('%jackson%')).first()
        main = Restaurant.query.filter(Restaurant.name.ilike('%main%')).first()

        print(f'Restaurants: {hale.name}, {jackson.name}, {main.name}')

        # ── HALE STREET ZONES ──
        hale_zones = [
            ('Walk-in', 'Walk-In Cooler', 'Monday', '06:00', 40),
            ('Behind Bar', None, None, None, 0),
            ('Basement', 'Basement Alcohol', 'Thursday', '07:00', 79),
            ('Freezer', 'Kitchen Freezer', 'Monday', '06:00', 12),
            ('Reach in Cooler', 'Kitchen Reach-In Refrigerator', 'Monday', '06:00', 2),
            ('Kitchen Line', 'Kitchen Line Coolers', 'Monday', '06:00', 12),
            ('Dry Storage Basement', 'Dry Storage basement', 'Monday', '06:00', 31),
            ('Dry Storage Kitchen', 'Dry Storage - Kitchen', 'Monday', '06:00', 36),
            ('Cubbies', 'Cubbies Behind Bar', 'Thursday', '10:00', 76),
            ('Bar Well/ Shelves', 'Bar Well and Shelves', 'Thursday', '10:00', 121),
            ('Bar Cooler', 'Bar Cooler', 'Thursday', '10:00', 41),
            ('Keg Room', 'New Count List', 'Thursday', '16:00', 40),
        ]
        for i, (zname, sname, cday, ctime, cnt) in enumerate(hale_zones):
            z = get_or_create_zone(hale.id, zname, cday, ctime, i)
            if sname:
                get_or_create_sheet(hale.id, z.id, sname, cnt, i)

        # ── JACKSON ZONES ──
        jackson_zones = [
            ('Back Cooler','Back Cooler','Monday','09:00',7),
            ('Black Locker','Locker By The fridge','Monday','09:00',28),
            ('Bottle Beer','Bottled Beer','Monday','09:00',32),
            ('Wine Back Up','Wine Back Up','Monday','09:00',14),
            ('Mixer Back Up','Mixer Back Up','Monday','09:00',12),
            ('K Shelf 1','K Shelf One','Monday','09:00',12),
            ('K Shelf 2','K Shelf Two','Monday','09:00',22),
            ('K Shelf 3','K Shelf Three','Monday','09:00',30),
            ('K Shelf 4','K Shelf Four','Monday','09:00',31),
            ('Red Bull Cooler','Red Bull Cooler','Monday','09:00',4),
            ('Beer Cooler','Beer Cooler','Monday','09:00',47),
            ('Service Well','Service Well','Monday','09:00',13),
            ('Mixers','Mixers','Monday','09:00',5),
            ('Red Wine Shelf','Red Wine Shelf','Monday','09:00',6),
            ('Cordials','Cordials','Monday','09:00',23),
            ('Scotch Shelf','Scotch Shelf','Monday','09:00',13),
            ('Liquor Shelf','Liquor Shelf','Monday','09:00',52),
            ('Front Cooler','Front Cooler','Monday','09:00',43),
            ('Tall Cage','Tall Cage','Monday','09:00',35),
            ('Walk-in','Walk In Cooler','Monday','09:00',61),
            ('Dry Storage','Dry Storage','Monday','09:00',48),
            ('Hallway','Hallway','Monday','09:00',6),
            ('Freezer','Freezer','Monday','09:00',17),
            ('Kitchen','Kitchen','Monday','09:00',36),
        ]
        for i, (zname, sname, cday, ctime, cnt) in enumerate(jackson_zones):
            z = get_or_create_zone(jackson.id, zname, cday, ctime, i)
            get_or_create_sheet(jackson.id, z.id, sname, cnt, i)

        # ── MAIN STREET ZONES ──
        main_zones = [
            ('Beer in Back','Beer in Back','Monday,Tuesday','08:00',47),
            ('Keg Cooler/Kegs','Beer Cooler','Monday,Tuesday','08:00',59),
            ('Mixer','Mixers','Tuesday','08:00',0),
            ('Upstairs','Upstairs','Monday,Tuesday','08:00',5),
            ('Liquor Cage','Liquor Cage','Monday,Tuesday','08:00',107),
            ('Dry Storage - Food','Dry Storage Food','Thursday','08:00',76),
            ('Dry Storage - Non Food','Dry Storage Non Food','Thursday','08:00',31),
            ('Walk-In Cooler','Walk In Cooler','Thursday','08:00',79),
            ('Kitchen Line','Kitchen Line','Thursday','08:00',48),
            ('Freezer','Freezer','Thursday','08:00',30),
            ('Wine Back Stock','New Count List','Thursday','08:00',14),
            ('Line cooler','Line Cooler','Thursday','08:00',0),
            ('Bar','BAR','Thursday','08:00',169),
        ]
        for i, (zname, sname, cday, ctime, cnt) in enumerate(main_zones):
            z = get_or_create_zone(main.id, zname, cday, ctime, i)
            get_or_create_sheet(main.id, z.id, sname, cnt, i)

        db.session.commit()

        for r in [hale, jackson, main]:
            items = InventoryItem.query.filter_by(restaurant_id=r.id).count()
            zones = StorageZone.query.filter_by(restaurant_id=r.id).count()
            sheets = CountSheet.query.filter_by(restaurant_id=r.id).count()
            print(f'{r.name}: {items} items, {zones} zones, {sheets} sheets')

        print('Seed complete.')
