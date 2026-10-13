"""Select a print orientation and write print-ready STLs (mm, lying on Z=0).

Orientation search: the 24 proper cube rotations are tried. For each, the
unsupported area is the area of downward-facing triangles steeper than 45 deg
from horizontal that are not on the build plate. Teardrop holes sit exactly at
45 deg, so they are not counted. The orientation with the smallest unsupported
area is used; ties go to the lower part height. Output files are written only
when the closed-mesh checks pass. This is a geometric screen, not a slicer run.
"""
import itertools, json, hashlib, math
from pathlib import Path
import numpy as np
import FreeCAD as App
import Mesh
import bearing_case as model
from mesh_checks import triangles

H = Path(__file__).resolve().parent
O = model.OUT
PRINT = O / 'print'
OVERHANG_COS = math.cos(math.radians(45.))
BED_TOL_MM = 0.05

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def proper_rotations():
    mats = []
    for perm in itertools.permutations(range(3)):
        for signs in itertools.product((1, -1), repeat=3):
            m = np.zeros((3, 3))
            for row, (col, s) in enumerate(zip(perm, signs)):
                m[row, col] = s
            if round(np.linalg.det(m)) == 1:
                mats.append(m)
    return mats

def face_stats(tris):
    n = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    area = np.linalg.norm(n, axis=1) / 2
    nn = n / np.maximum(np.linalg.norm(n, axis=1), 1e-12)[:, None]
    zmin = tris[:, :, 2].min(axis=1)
    on_bed = (tris[:, :, 2].max(axis=1) < BED_TOL_MM)
    overhang = (nn[:, 2] < -OVERHANG_COS) & (~on_bed)
    bed_area = float(area[on_bed & (nn[:, 2] < -0.99)].sum())
    return {
        'unsupported_overhang_area_mm2': float(area[overhang].sum()),
        'bed_contact_area_mm2': bed_area,
        'height_mm': float(tris[:, :, 2].max() - tris[:, :, 2].min()),
    }

def place(tris, R):
    rot = tris.reshape(-1, 3) @ R.T
    rot = rot.reshape(tris.shape)
    shift = np.array([-(rot[:, :, 0].min() + rot[:, :, 0].max()) / 2,
                      -(rot[:, :, 1].min() + rot[:, :, 1].max()) / 2,
                      -rot[:, :, 2].min()])
    return rot + shift

def choose_orientation(tris, allowed):
    """Pick the best orientation among those where allowed(R) holds.

    Also returns the unconstrained best for information. Constraints keep the
    bearing-seat and head-tunnel axes horizontal in print, so the teardrop roofs
    are the intended overhang geometry.
    """
    rows = []
    for R in proper_rotations():
        placed = place(tris, R)
        stats = face_stats(placed)
        rows.append((stats["unsupported_overhang_area_mm2"], stats["height_mm"], R, stats, bool(allowed(R))))
    rows.sort(key=lambda r: (round(r[0], 3), r[1]))
    constrained = [r for r in rows if r[4]]
    best = constrained[0]
    table = [{'rotation_row_major': R.round().astype(int).tolist(), 'allowed': ok, **stats}
             for _, _, R, stats, ok in rows]
    unconstrained = rows[0]
    return best[2], best[3], table, unconstrained

XY_ROUNDING_SHIFTS_MM = [(0.0, 0.0)] + [(x * 1e-4, y * 1e-4) for x in (-3, -2, -1, 0, 1, 2, 3) for y in (-3, -2, -1, 0, 1, 2, 3) if (x, y) != (0, 0)]

def write_binary_stl(tris, path):
    """Binary STL straight from the placed triangles (FreeCAD constructor crashes on lists)."""
    import struct
    n = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    n = n / np.maximum(np.linalg.norm(n, axis=1), 1e-30)[:, None]
    with open(path, 'wb') as fh:
        fh.write(b'binary STL written by export_print.py, units mm'.ljust(80, b' '))
        fh.write(struct.pack('<I', len(tris)))
        for normal, f in zip(n, tris):
            fh.write(struct.pack('<12fH', *normal.astype(np.float32), *f.astype(np.float32).ravel(), 0))

def mesh_checks(mesh, expected_volume, label):
    tris = triangles(mesh)
    z_min = float(tris[:, :, 2].min())
    xy_centre = [float((tris[:, :, 0].min() + tris[:, :, 0].max()) / 2),
                 float((tris[:, :, 1].min() + tris[:, :, 1].max()) / 2)]
    rec = {
        'label': label,
        'facets': int(mesh.CountFacets),
        'components': int(mesh.countComponents()),
        'closed': bool(mesh.isSolid()),
        'non_manifold': bool(mesh.hasNonManifolds()),
        'self_intersections': int(len(mesh.getSelfIntersections())),
        'min_z_mm': z_min,
        'xy_centre_mm': xy_centre,
        'volume_mm3': float(mesh.Volume),
        'expected_volume_mm3': float(expected_volume),
    }
    rec['pass'] = bool(
        rec['components'] == 1 and rec['closed'] and not rec['non_manifold']
        and rec['self_intersections'] == 0 and abs(z_min) < 1e-6
        and abs(xy_centre[0]) < 1e-3 and abs(xy_centre[1]) < 1e-3
        and abs(rec['volume_mm3'] - expected_volume) < 1e-3 * expected_volume
    )
    return rec

def export(source_name, out_name, label, allowed, constraint):
    mesh = Mesh.Mesh(str(O / source_name))
    tris = triangles(mesh)
    expected = float(mesh.Volume)
    R, stats, table, unconstrained = choose_orientation(tris, allowed)
    placed = place(tris, R)
    # Moving float32 vertices re-rounds them, which can bring back one nearly
    # touching self-intersection that the case export had removed. Try XY
    # shifts far below the 1e-3 mm centring tolerance; Z is never shifted.
    for shift in XY_ROUNDING_SHIFTS_MM:
        write_binary_stl(placed + np.array([shift[0], shift[1], 0.0]), PRINT / out_name)
        check = mesh_checks(Mesh.Mesh(str(PRINT / out_name)), expected, label)
        if check['pass']:
            break
    check.update(xy_rounding_shift_mm=list(shift), stats=stats, orientation_row_major=R.round().astype(int).tolist(),
                 constraint=constraint,
                 unconstrained_best={'unsupported_overhang_area_mm2': unconstrained[3]['unsupported_overhang_area_mm2'],
                                     'rotation_row_major': unconstrained[2].round().astype(int).tolist()},
                 candidate_orientations=table[:5], candidate_count=len(table),
                 source=source_name, output=f'print/{out_name}', output_sha256=sha(PRINT / out_name))
    if not check['pass']:
        raise RuntimeError(f'print export failed closed-mesh/placement check: {label}: ' + json.dumps({k: v for k, v in check.items() if k not in ('candidate_orientations',)}))
    return check

def bed_face_description(R):
    """Source-frame normal of the face that lies on the build plate."""
    normal = -R[2]
    names = {(1, 0, 0): '+X', (-1, 0, 0): '-X', (0, 1, 0): '+Y', (0, -1, 0): '-Y',
             (0, 0, 1): '+Z', (0, 0, -1): '-Z'}
    return names[tuple(int(round(x)) for x in normal)]

def hole_axis_tilt(R):
    """Largest tilt (deg) of the bearing-seat axes from the build plate in this orientation."""
    from types import SimpleNamespace
    frames = model.frames(SimpleNamespace(**model.DEFAULTS))
    R = np.asarray(R, dtype=float)
    return max(math.degrees(math.asin(min(1.0, abs(float((R @ np.array([ax.x, ax.y, ax.z]))[2])))))
               for _, ax, _ in frames)

def support_text(area, part):
    if area < 5.0:
        return (f"サポート: スクリーン上は不要（45度超の未支持面 {area:.1f} mm2）。"
                "FlashPrintのプレビューで確認する。")
    return (f"サポート: 必要。スクリーン上の45度超の未支持面は {area:.1f} mm2（{part}）。"
            "FlashPrintでサポートを有効にし、ベアリング座とネジ穴の内部、水平の屋根に入り込まない位置をプレビューで確認する。")

def write_print_md(case, coupon):
    cs, ks = case['stats'], coupon['stats']
    lines = [
        '# FlashPrint 印刷メモ（PLA・0.4 mm ノズル）',
        '',
        '単位はすべてmm。STLはXYの中心を原点付近に置き、最低点をZ=0にしてある。',
        'この文書とSTLは形状の検査結果であり、印刷可能性・嵌合・強度の合格ではない。',
        '',
        '## ファイル',
        '',
        '| ファイル | 内容 | 印刷 |',
        '|---|---|---|',
        '| `trackball_bearing_case_print.stl` | 34 mmボール用ベアリングケース本体（ボス3点・ボール側クリアランス・ネジ穴・収納ボス） | する（1個） |',
        '| `fit_coupon_print.stl` | 3段の組付け試験片（ネジ穴径・ベアリング座の逃げ量の比較用。段の順序は下表） | する（1個） |',
        '',
        '印刷対象外（このフォルダーに置いていない）: 金属スペーサー・ベアリング・ビス・ボール（寸法参照用の `inner_ring_spacer.stl` 等は `generated/` 側）。',
        '',
        '## 試験片の段（左から順）',
        '',
        '| 段 | ベアリング座の逃げ | 下穴径 | 注意 |',
        '|---|---|---|---|',
        '| 1（左） | 0.20 mm | 2.05 mm | ネジのタップ用に小さい側 |',
        '| 2（中） | 0.30 mm | 2.15 mm | 設計値 |',
        '| 3（右） | 0.40 mm | 2.25 mm | ネジが緩くなる側 |',
        '',
        '## 印刷設定（FlashPrintで手動設定）',
        '',
        '- 材料: PLA。ノズル温度 200〜210 °C、ベッド温度 50〜60 °C（フィラメントの指定範囲を優先）',
        '- ノズル 0.4 mm、層の高さ 0.2 mm',
        '- 壁: 外周 3本以上（線幅換算 1.2 mm以上）',
        '- インフィル 30〜40%（gyroid）',
        f"- ケース本体: {support_text(cs['unsupported_overhang_area_mm2'], 'ドーム形状の下向き面。位置は未特定')}",
        f"- 試験片: {support_text(ks['unsupported_overhang_area_mm2'], '未支持の丸穴の底面が主因と推定')}",
        f"- ブリム: ケース本体のベッド接触面積 {cs['bed_contact_area_mm2']:.0f} mm2。"
        + ('接触が小さいため、反り防止に5 mmブリムを推奨。' if cs['bed_contact_area_mm2'] < 400 else 'ブリムは任意。')
        + f" 試験片のベッド接触面積は {ks['bed_contact_area_mm2']:.0f} mm2。",
        '- 底面の象足: 試験片の底面に0.3 mmの面取りを入れてある。',
        '',
        '## 向き',
        '',
        f"- ケース本体: 造形面（ベッド）に置くのは元形状の {bed_face_description(np.array(case['orientation_row_major']))} 方向の面（元形状の フランジ下面）。"
        f" 造形高さ {cs['height_mm']:.1f} mm。 向きの条件: ベアリング軸を水平に保つため、造形Zを元形状のZ軸に揃えた。",
        f"- 試験片: 造形面に置くのは元形状の {bed_face_description(np.array(coupon['orientation_row_major']))} 方向の面（底の面）。"
        f" 造形高さ {ks['height_mm']:.1f} mm。 向きの条件: 穴の軸を水平に保つため、造形Zを元形状のY軸に直交させた。",
        f"- ベアリング座とネジ穴の軸は、この向きで造形面に対して最大 {hole_axis_tilt(case['orientation_row_major']):.1f} 度傾く（0度が水平）。",
        '- ベアリング座とネジ穴の天井は45度の屋根（ティアドロップ）。水平の穴は屋根が45度を超えないことを前提にしている。',
        '- 向きはスライサーで必ずプレビューし、ベッド接触が面になっているか確認する。',
        '',
        '## 未確認事項',
        '',
        '- 印刷結果（寸法・反り・層間剥離）は未確認。試し刷りが必要。',
        '- 嵌合（ベアリング・ネジ・ボール）と強度・耐久性は未確認。',
        '- ボール側のボス薄肉（約0.58 mm）は目標1.6 mm、下限1.2 mmに満たない。詳細はverification.jsonとREADMEを参照。',
        '- FlashPrintのプロファイル名と生成G-codeは作っていない。',
    ]
    (PRINT / 'PRINT.md').write_text(chr(10).join(lines) + chr(10), encoding='utf-8')

def main():
    PRINT.mkdir(parents=True, exist_ok=True)
    # Case: bearing axes are horizontal in the source frame, so print Z must stay
    # the source Z axis (+/-). Coupon: holes run along source Y, so print Z must
    # stay perpendicular to Y.
    case = export('trackball_bearing.stl', 'trackball_bearing_case_print.stl', 'case body',
                  lambda R: abs(R[2, 0]) < 1e-9 and abs(R[2, 1]) < 1e-9,
                  'print Z parallel to source Z (bearing axes stay horizontal)')
    coupon = export('fit_coupon.stl', 'fit_coupon_print.stl', 'fit coupon',
                    lambda R: abs(R[2, 1]) < 1e-9,
                    'print Z perpendicular to source Y (holes stay horizontal)')
    write_print_md(case, coupon)
    evidence = {'status': 'PRINT_FILES_CHECKED_PHYSICAL_UNVERIFIED', 'units': 'mm',
                'method': 'cube-rotation search; 45 deg overhang screen; watertight/placement checks',
                'overhang_threshold_deg': 45.0, 'bed_tolerance_mm': BED_TOL_MM,
                'parts': [case, coupon]}
    (O / 'print_evidence.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
    print(json.dumps({'case': case['pass'], 'coupon': coupon['pass'],
                      'case_overhang_mm2': case['stats']['unsupported_overhang_area_mm2'],
                      'coupon_overhang_mm2': coupon['stats']['unsupported_overhang_area_mm2']}), flush=True)

if __name__ == '__main__':
    main()
