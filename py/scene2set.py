#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scene.json -> .set (set.a.light 3D V3).  Использование: scene2set.py scene.json out.set

ПЛАН-СИСТЕМА scene.json (вид сверху, север вверху):
  x — метры от ЗАПАДНОЙ стены на восток;  d — метры от СЕВЕРНОЙ стены на юг.
  facing_deg — компас, куда смотрит ПЕРЕД предмета: 0=север, 90=восток, 180=юг, 270=запад.
  width — размер поперёк взгляда, depth — вдоль взгляда, height — высота. elevation — низ над полом.
Мир .set (Unity, левосторонняя): X = x - L/2 (восток=+X), Z = -d (север = +Z), y от пола.
Порталы проверены только на стенах east (wall 5, rot 90) и west (wall 4, rot 270); если порталы
на north/south — сцена поворачивается на 90°, чтобы они стали east/west.
"""
import sys, os, json, copy, math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import set_codec as sc
except ImportError:
    from . import set_codec as sc

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = '/Users/misharenne/Downloads/3d/Project-2603231337 (5) (1).set'
CAT = json.load(open(os.path.join(HERE, 'catalog.json')))
CAL = CAT['calibration']
WALL_NEXT = {'north': 'east', 'east': 'south', 'south': 'west', 'west': 'north'}


def fl(seq):
    return [float(v) for v in seq]


def rotate_cw(scene):
    """Повернуть план на 90° по часовой: север -> восток."""
    s = copy.deepcopy(scene)
    r = s['room']
    ew, ns = r['size_ew'], r['size_ns']
    r['size_ew'], r['size_ns'] = ns, ew
    for o in s.get('objects', []) + s.get('lights', []):
        o['x'], o['d'] = ns - o['d'], o['x']
        if 'facing_deg' in o:
            o['facing_deg'] = (o['facing_deg'] + 90) % 360
    for p in s.get('portals', []):
        c = p['center']
        # north->east: along north (from west) -> along east (from north) = c
        # east->south: along east (from north) -> along south (from west) = ns - c
        # south->west: along south (from west) -> along west (from north) = c
        # west->north: along west (from north) -> along north (from west) = ns - c
        if p['wall'] in ('east', 'west'):
            p['center'] = ns - c
        p['wall'] = WALL_NEXT[p['wall']]
    return s


def normalize(scene, warnings):
    ps = scene.get('portals', [])
    ns_n = sum(1 for p in ps if p['wall'] in ('north', 'south'))
    ew_n = len(ps) - ns_n
    if ns_n and not ew_n:
        scene = rotate_cw(scene)
        warnings.append('сцена повёрнута на 90° (порталы были на north/south, номера этих стен не проверены)')
    elif ns_n and ew_n:
        keep = [p for p in ps if p['wall'] in ('east', 'west')]
        dropped = [p for p in ps if p['wall'] not in ('east', 'west')]
        scene = copy.deepcopy(scene); scene['portals'] = keep
        warnings.append('порталы на north/south пропущены (%d шт.): рядом есть east/west' % len(dropped))
    return scene


def build_bytes(scene, template_bytes=None):
    """scene(dict) -> (байты .set, предупреждения). template_bytes — шаблон .set (по умолчанию кухонный файл)."""
    warnings = []
    scene = normalize(scene, warnings)
    r = scene['room']
    L, W, H = r['size_ew'], r['size_ns'], r['height']
    header, tree = sc.load_bytes(template_bytes if template_bytes is not None else open(TEMPLATE, 'rb').read())
    us = tree['timeline']['unsavedSet']
    objs = us['objects']
    room, g_light, g_props = objs[0], objs[2], objs[4]
    assert g_props['data'][1]['nameKey'] == 'CATEGORY_PROPS' and g_light['data'][1]['nameKey'] == 'CATEGORY_LIGHTSOURCES'
    def first(pred):
        return copy.deepcopy(next(o for o in objs if pred(o)))
    t_chair = first(lambda o: o['data'][0] == 4)
    t_block = first(lambda o: o['data'][0] == 13)
    t_win = first(lambda o: o['data'][0] == 22 and 'door' not in o['name'])
    t_door = first(lambda o: o['data'][0] == 22 and 'door' in o['name'])
    t_lamp = first(lambda o: o['data'][0] == 8)
    objs[:] = objs[:5]
    room['childObjects'] = []; g_props['childObjects'] = []; g_light['childObjects'] = []

    def new(tmpl, name, parent):
        o = copy.deepcopy(tmpl); o['ID'] = sc.new_id(); o['name'] = name; o['childObjects'] = []
        objs.append(o); parent['childObjects'].append(o['ID']); return o

    rd = room['data'][1]
    rd['size'] = fl((L, H, W))
    gain = CAL['floor_gain']
    if r.get('floor_color'):
        g_ = [1.0, 1.0, 1.0] if r.get('_floor_is_app_color') else gain      # цвет с фото -> цвет приложения
        rd['floorColor'] = [min(1.0, c * g) for c, g in zip(r['floor_color'], g_)] + [1.0]
    if r.get('wall_color'):
        rd['wallColor'] = fl(r['wall_color'][:3]) + [1.0]
    if r.get('ceiling_color'):
        rd['ceilingColor'] = fl(r['ceiling_color'][:3]) + [1.0]

    def world(o):
        return o['x'] - L / 2, -o['d']

    for o in scene.get('objects', []):
        cat = o['category']
        X, Z = world(o)
        y = float(o.get('elevation', 0.0))
        facing = float(o.get('facing_deg', 0.0))
        name = o.get('name') or cat
        a = CAT['assets'].get(cat)
        if a:
            ob = new(t_chair, name, g_props)
            d = ob['data']; d[1]['asset'] = bytes.fromhex(a['asset']); d[1]['materialSettings'] = []
            sc_ = list(a['default_scale'])
            if a.get('base'):
                sc_ = [o['width'] / a['base'][0], 1.0, o['depth'] / a['base'][1]]
            d[1]['scale'] = fl(sc_)
            yaw = (facing - a['front_yaw0_compass']) % 360
        else:
            ob = new(t_block, name, g_props)
            d = ob['data']
            d[1]['size'] = fl((o['width'], o['depth'], o['height']))
            d[1]['color'] = fl(o.get('color') or CAT['block_default_color'])[:3] + [1.0]
            yaw = facing % 360
        ob['position'] = fl((X, y, Z)); ob['rotation'] = fl((0.0, yaw, 0.0))

    off = CAL['portal_wall_offset']
    for p in scene.get('portals', []):
        tmpl = t_door if p['kind'] == 'door' else t_win
        ob = new(tmpl, p['kind'], room)
        d = ob['data'][1]
        zc = -p['center']                       # вдоль стены от северного конца
        bottom = float(p.get('bottom', 0.0))
        if p['wall'] == 'east':
            ob['position'] = fl((L / 2 + off, bottom, zc)); ob['rotation'] = fl((0, 90, 0))
            d['wall'] = CAL['wall_ids']['east']; d['position'] = fl((zc + W, bottom))
        else:
            ob['position'] = fl((-L / 2 - off, bottom, zc)); ob['rotation'] = fl((0, 270, 0))
            d['wall'] = CAL['wall_ids']['west']; d['position'] = fl((-zc, bottom))
        d['size'] = fl((p['width'], p['height']))

    for l in scene.get('lights', []) or [{'x': L / 2, 'd': W / 2, 'height': H - 0.25}]:
        ob = new(t_lamp, 'ceiling light', g_light)
        X, Z = world(l)
        ob['position'] = fl((X, l.get('height', H - 0.25), Z))

    return sc.dump_bytes(header, tree), warnings


def build(scene, out, template_bytes=None):
    data, warnings = build_bytes(scene, template_bytes)
    with open(out, 'wb') as fh:
        fh.write(data)
    assert sc.verify_roundtrip(out)
    return warnings


if __name__ == '__main__':
    scene = json.load(open(sys.argv[1]))
    w = build(scene, sys.argv[2])
    print('записано', sys.argv[2])
    for x in w: print('! ', x)
