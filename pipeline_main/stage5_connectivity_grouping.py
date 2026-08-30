import json
import os
import time
from shapely.geometry import Polygon, Point
from shapely.strtree import STRtree

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PUZZLE_DIR = os.path.dirname(SCRIPT_DIR)

METAL_FILE = os.path.join(PUZZLE_DIR, "output_main", "stage4_routing_geometry.json")
CONTACT_FILE = os.path.join(PUZZLE_DIR, "output_main", "stage4b_contacts.json")
FOOTPRINT_FILE = os.path.join(PUZZLE_DIR, "output_main", "stage1c_instance_footprints.json")
OUTPUT_FILE = os.path.join(PUZZLE_DIR, "output_main", "stage5_nets.json")

LAYER_ORDER = ["li1", "met1", "met2", "met3", "met4", "met5"]
CHIPWIDE_MERGE_LAYERS = ["met1", "met2", "met3", "met4", "met5"]
TOUCH_TOL = 0.005


class UnionFind:
    def __init__(self):
        self.parent = {}

    def find(self, x):
        if x not in self.parent:
            self.parent[x] = x
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def to_shapely(poly_pts):
    return Polygon(poly_pts).buffer(TOUCH_TOL)


def main():
    t0 = time.time()
    print("=== PUZZLE STAGE 5 (shapely, per-instance li1 scoping) ===\n")

    with open(METAL_FILE) as f:
        metal = json.load(f)
    with open(CONTACT_FILE) as f:
        contacts = json.load(f)
    with open(FOOTPRINT_FILE) as f:
        footprints = json.load(f)

    print("Building shapely geometry for all shapes...")
    nodes = []
    for layer in LAYER_ORDER:
        for idx, poly in enumerate(metal.get(layer, [])):
            nodes.append((layer, idx, to_shapely(poly)))

    by_layer = {l: [] for l in LAYER_ORDER}
    for nid, (layer, idx, geom) in enumerate(nodes):
        by_layer[layer].append(nid)

    print(f"Total shapes loaded: {len(nodes)} ({time.time()-t0:.1f}s)")
    for layer in LAYER_ORDER:
        print(f"  {layer}: {len(by_layer[layer])}")

    uf = UnionFind()

    print("\nChip-wide same-layer merge (met1-met5)...")
    for layer in CHIPWIDE_MERGE_LAYERS:
        t1 = time.time()
        ids = by_layer[layer]
        geoms = [nodes[nid][2] for nid in ids]
        tree = STRtree(geoms)
        merges = 0
        for i, geom in enumerate(geoms):
            for j in tree.query(geom):
                if j <= i:
                    continue
                if geom.intersects(geoms[j]):
                    uf.union(ids[i], ids[j])
                    merges += 1
        print(f"  {layer}: {merges} merges ({len(ids)} shapes, {time.time()-t1:.1f}s)")

    print("\nPer-instance li1 merge (scoped to each cell's footprint)...")
    t1 = time.time()
    li1_ids = by_layer["li1"]
    li1_geoms = {nid: nodes[nid][2] for nid in li1_ids}
    # Build spatial index of li1 centroids for fast footprint-membership lookup
    li1_centroid_list = [(nid, li1_geoms[nid].centroid) for nid in li1_ids]
    total_li1_merges = 0
    claimed = set()
    for fp in footprints:
        bx0, by0, bx1, by1 = fp["bbox"]
        instance_shapes = [nid for nid, c in li1_centroid_list if bx0 <= c.x <= bx1 and by0 <= c.y <= by1]
        geoms_local = [li1_geoms[nid] for nid in instance_shapes]
        if len(geoms_local) < 2:
            claimed.update(instance_shapes)
            continue
        tree = STRtree(geoms_local)
        for i, geom in enumerate(geoms_local):
            for j in tree.query(geom):
                if j <= i:
                    continue
                if geom.intersects(geoms_local[j]):
                    uf.union(instance_shapes[i], instance_shapes[j])
                    total_li1_merges += 1
        claimed.update(instance_shapes)
    unclaimed_li1 = len(li1_ids) - len(claimed)
    print(f"  Total li1 merges: {total_li1_merges} ({time.time()-t1:.1f}s)")
    print(f"  li1 shapes unclaimed by any footprint: {unclaimed_li1} ({100*unclaimed_li1/len(li1_ids):.1f}%)")

    print("\nBuilding spatial indices for contact bridging...")
    trees = {}
    for layer in LAYER_ORDER:
        ids = by_layer[layer]
        geoms = [nodes[nid][2] for nid in ids]
        trees[layer] = (STRtree(geoms), ids, geoms)

    print("Cross-layer bridging via contacts...")
    t1 = time.time()
    total_bridges = 0
    for cname, entries in contacts.items():
        below, above = (entries[0]["connects"] if entries else [None, None])
        if below not in LAYER_ORDER or above not in LAYER_ORDER:
            print(f"  {cname}: skipped ({below} <-> {above} not in scope)")
            continue
        tree_b, ids_b, geoms_b = trees[below]
        tree_a, ids_a, geoms_a = trees[above]
        hits = 0
        for c in entries:
            px, py = c["position"]
            pt = Point(px, py)
            nb, na = None, None
            for j in tree_b.query(pt):
                if geoms_b[j].contains(pt):
                    nb = ids_b[j]
                    break
            for j in tree_a.query(pt):
                if geoms_a[j].contains(pt):
                    na = ids_a[j]
                    break
            if nb is not None and na is not None:
                uf.union(nb, na)
                hits += 1
        total_bridges += hits
        print(f"  {cname}: {hits}/{len(entries)} bridged  [{below} <-> {above}]")

    print(f"\nTotal successful bridges: {total_bridges} ({time.time()-t1:.1f}s)")

    print("\nCollecting nets...")
    groups = {}
    for nid in range(len(nodes)):
        groups.setdefault(uf.find(nid), []).append(nid)

    nets = []
    for root, members in groups.items():
        nets.append({
            "size": len(members),
            "members": [{"layer": nodes[m][0], "index": nodes[m][1]} for m in members],
        })
    nets.sort(key=lambda n: -n["size"])

    print(f"Total nets formed: {len(nets)}")
    print("Top 15 net sizes:", [n["size"] for n in nets[:15]])
    print("Bottom 10 net sizes:", [n["size"] for n in nets[-10:]])

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(nets, f, indent=2)

    print(f"\n✓ Saved to {OUTPUT_FILE}")
    print(f"Total runtime: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
