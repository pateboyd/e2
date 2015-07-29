import collections
import dbm
import logging; log = logging.getLogger('qmsk.e2.presets')
import os
import os.path

from xml.etree import ElementTree

class Error(Exception):
    pass

class XMLError(Error):
    pass

def parse_xml_aux_dest (xml):
    """
        <AuxDest>
            <OutCfgIndex>
            <Name>
    """

    index = (int(xml.find('OutCfgIndex').text), )

    return ('destinations', index, {
            'title': xml.find('Name').text,
    })
    
def parse_xml_screen_dest_index (xml):
    """
        <ScreenDest><DestOutMapCol><DestOutMap>
            <OutCfgIndex>
    """
    for xml_dest_out_map in xml.find('DestOutMapCol').findall('DestOutMap'):
        yield int(xml_dest_out_map.find('OutCfgIndex').text)

def parse_xml_screen_dest (xml):
    """
        <ScreenDest>
            <Name>
    """

    index = tuple(
        int(xml_dest_out_map.find('OutCfgIndex').text)
            for xml_dest_out_map_col in xml.findall('DestOutMapCol')
                for xml_dest_out_map in xml_dest_out_map_col.findall('DestOutMap')
    )

    return ('destinations', index, {
            'title': xml.find('Name').text,
    })

def parse_xml_settings (xml):
    """
        <System>
            <DestMgr>
    """
    if xml.tag != 'System':
        raise XMLError("Unexpected preset root node: {xml}".format(xml=xml))

    xml_dest_mgr = xml.find('DestMgr')

    for xml_aux_dest_col in xml_dest_mgr.findall('AuxDestCol'):
        for xml_aux_dest in xml_aux_dest_col.findall('AuxDest'):
            yield parse_xml_aux_dest(xml_aux_dest)
    
    for xml_screen_dest_col in xml_dest_mgr.findall('ScreenDestCol'):
        for xml_screen_dest in xml_screen_dest_col.findall('ScreenDest'):
            yield parse_xml_screen_dest(xml_screen_dest)

def parse_xml_preset (xml):
    """
        Parse XML dump <Preset> and return { }
    """

    index = int(xml.attrib['id']) + 1
    title = xml.find('Name').text
    destinations = []

    if '@' in title:
        title, group = title.split('@')
        title = title.strip()
        group = group.strip()
    else:
        group = None

    for xml_screen_dest_col in xml.findall('ScreenDestCol'):
        for xml_screen_dest in xml_screen_dest_col.findall('ScreenDest'):
            type, destination_index, items = parse_xml_screen_dest(xml_screen_dest)

            destinations.append(destination_index)

    for xml_aux_dest_col in xml.findall('AuxDestCol'):
        for xml_aux_dest in xml_aux_dest_col.findall('AuxDest'):
            type, destination_index, items = parse_xml_aux_dest(xml_aux_dest)

            destinations.append(destination_index)

    return ('presets', index, {
            'group': group,
            'destinations': destinations,
            'title': title,
    })

def parse_xml_presets (xml):
    """
        Load an XML dump <PresetMgr> root element and load the <Preset>s
    """

    if xml.tag != 'PresetMgr':
        raise XMLError("Unexpected preset root node: {xml}".format(xml=xml))
    
    for xml_preset in xml.findall('Preset'):
        yield parse_xml_preset(xml_preset)

def parse_xml (xml_dir):
    # settings
    xml_settings = os.path.join(xml_dir, 'settings_backup.xml')

    log.debug("%s", xml_settings)

    for item in parse_xml_settings(ElementTree.parse(xml_settings).getroot()):
        yield item
    
    # presets
    xml_presets = os.path.join(xml_dir, 'presets')

    for name in os.listdir(xml_presets):
        xml_preset = os.path.join(xml_presets, name)

        log.debug("%s", xml_preset)

        for item in parse_xml_presets(ElementTree.parse(xml_preset).getroot()):
            yield item

class Destination:
    def __init__ (self, index, *, title):
        self.index = index

        self.title = title
        
        self.preview = self.program = None

    def __lt__ (self, preset):
        return self.title < preset.title 
   
    def __str__ (self):
        return "{self.title}".format(self=self)

class Preset:
    """
        index:int                       E2's internal preset ID
        group:Group                     grouped presets
        destinations:[Destination]      Destinations included in this preset
        title:string                    human-readable title
    """
    def __init__ (self, index, group, destinations, *, title):
        self.index = index
        self.group = group
        self.destinations = destinations

        self.title = title

    def __lt__ (self, preset):
        return self.title < preset.title 

    def __str__ (self):
        return "{self.title} @ {self.group}".format(self=self)

class Group:
    def __init__ (self, index, *, title):
        self.index = index
        
        self.title = title
        self._presets = []

    def _add_preset (self, preset):
        self._presets.append(preset)

    @property
    def presets (self):
        return tuple(sorted(self._presets))

    def __str__ (self):
        if self.title is None:
            return "Ungrouped"
        else: 
            return self.title

class DBProperty:
    def __init__ (self, name):
        self.name = name

    def __get__ (self, obj, type=None):
        log.debug("%s", self.name)

        return obj.db.get(self.name)

    def __set__ (self, obj, value):
        log.debug("%s: %s", self.name, value)

        obj.db[self.name] = value

    def __del__ (self, obj):
        log.debug("%s", self.name)

        del obj.db[self.name]

class DB:
    def __init__(self, db, dump, load):
        self.db = db
        self.dump = dump
        self.load = load

    def key(self, key):
        if not isinstance(key, tuple):
            key = (key, )
        
        return '/'.join(str(k) for k in key)

    def __getitem__ (self, key):
        return self.load(self.db[self.key(key)])

    def get(self, *key):
        value = self.db.get(self.key(key))

        if value:
            return self.load(value)
        else:
            return None

    def __setitem__ (self, key, value):
        self.db[self.key(key)] = self.dump(value)

class Presets:
    """
        Load the Encore2 Presets database and implement a state machine for recalling/transitioning Presets.
    """

    @classmethod
    def load (cls, xml_dir, db=None):
        data = collections.defaultdict(lambda: collections.defaultdict(list))
    
        for type, index, item in parse_xml(xml_dir):
            log.debug("%s @ %s = %s", type, index, item)

            items = data[type]

            if index in items:
                raise XMLError("Duplicate {type}: {index}: {item}".format(type=type, index=index, item=item))

            items[index] = item

        if db:
            log.debug("%s", db)

            db = dbm.open(db, 'c')

        return cls(db, **data)

    def __init__ (self, db, destinations, presets):
        self._destinations = { }
        self._presets = { }

        self._groups = { }
        self.default_group = Group(None, title=None)

        # load
        for index, item in destinations.items():
            self._destinations[index] = Destination(index, **item)

        for index, item in presets.items():
            self._load_preset(index, **item)

        # state
        self.db = db
        self.db_presets = DB(db,
                load    = lambda index: self._presets[int(index)],
                dump    = lambda preset: str(preset.index),
        )

        self.active = self.db_presets.get('active')

        log.info("Active preset: %s", self.active)

        for destination in self._destinations.values():
            destination.preview = self.db_presets.get('preview', destination.index)
            destination.program = self.db_presets.get('program', destination.index)

        # events
        self._notify = set()

    def _load_group (self, title):
        index = title.lower()

        group = self._groups.get(index)

        if group is None:
            log.info("%s: %s", index, title)

            group = self._groups[index] = Group(index, title=title)
        
        return group

    def _load_preset (self, index, group=None, destinations=(), **item):
        """
            Load the given series of { 'preset': int, **opts } into (unique) Preset items.

                preset: int
                group: Group
        """

        log.info("%s: %s @ %s = %s", index, item.get('title'), group, ' + '.join(str(d) for d in destinations))

        if index in self._presets:
            raise Error("Duplicate preset: {index} = {item}".format(index=index, item=item))

        if group:
            group = self._load_group(group)
        else:
            group = self.default_group

        destinations = [self._destinations[index] for index in destinations]
        
        preset = self._presets[index] = Preset(index, group=group, destinations=destinations, **item)

        group._add_preset(preset)

        return preset

    # events
    def add_notify(self, func):
        log.info("%s", func)

        self._notify.add(func)

    def del_notify(self, func):
        log.info("%s", func)

        self._notify.remove(func)

    def notify(self):
        log.info("")

        for func in self._notify:
            try:
                func()
            except Exception as error:
                log.exception("%s: %s", func, error)

    # state
    def activate_preview (self, preset):
        """
            Activate the given preset. Updates the preview for the preset's destinations, and the active preset for activate_program().

            Returns the active preset, or None if unknown.
        """

        self.active = self.db_presets['active'] = preset

        for destination in preset.destinations:
            log.info("%s: %s -> %s", destination, destination.preview, preset)

            destination.preview = self.db_presets['preview', destination.index] = preset
    
        self.notify()

        return preset

    def activate_program (self):
        """
            Take the currently active preset (from activate_preview(preset)) to program for its destinations.
            The currently active preset remains active.
        """

        preset = self.active
        
        for destination in preset.destinations:
            log.info("%s: %s -> %s", destination, destination.program, preset)

            destination.program = self.db_presets['program', destination.index] = preset
        
        self.notify()

        return preset
 
    def close(self):
        if self.db:
            self.db.close()
   
    # query
    @property
    def groups (self):
        yield self.default_group

        for name, group in sorted(self._groups.items()):
            yield group

    @property
    def destinations (self):
        for name, obj in sorted(self._destinations.items()):
            yield obj

    def __iter__ (self):
        for preset in self._presets.values():
            yield preset

    def __getitem__ (self, key):
        return self._presets[key]

    def __len__ (self):
        return len(self._presets)

import argparse

def parser (parser):
    group = parser.add_argument_group("qmsk.e2.presets Options")
    group.add_argument('--e2-presets-xml', metavar='PATH',
        help="Load presets from XML backup dump directory")
    group.add_argument('--e2-presets-db', metavar='PATH',
        help="Store preset state in db")

def apply (args):
    presets = Presets.load(
        xml_dir     = args.e2_presets_xml,
        db          = args.e2_presets_db,
    )

    return presets

