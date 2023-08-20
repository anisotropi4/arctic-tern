#!/usr/bin/env python

import datetime as dt
from functools import partial

import geopandas as gp
import numpy as np
import pandas as pd
import rasterio as rio
import rasterio.features as rif
from shapely import (
    get_coordinates,
    line_merge,
    segmentize,
    set_precision,
    simplify,
    unary_union,
)
from shapely.affinity import affine_transform
from shapely.geometry import LineString, MultiLineString, Point
from skimage.morphology import remove_small_holes, skeletonize

pd.set_option("display.max_columns", None)

START = dt.datetime.now()

OUTPATH = "dx3.gpkg"
CRS = "EPSG:27700"

AFFINE_ONE = np.asarray([1.0, 0.0, 1.0, 0.0, -1.0, 1.0])
# SCALE = 4.0
SCALE = 0.5
BUFFER = 8.0


def log(this_string):
    """print timestamp appended to 'this_string'
    :param this_string:
    """
    now = dt.datetime.now() - START
    print(this_string + f"\t{now}")


def get_affine_transform(r, transform=AFFINE_ONE):
    return affine_transform(r, transform)


def get_dimension(this_gf):
    r = this_gf.total_bounds
    return np.ceil(np.diff(r.reshape(-1, 2), axis=0).reshape(-1))


def get_affine_transform(this_gf, scale=1.0):
    bound = this_gf.total_bounds
    r = AFFINE_ONE / scale
    r[2] = bound[0]
    r[5] = bound[3]
    r = rio.Affine(*r)
    s = get_dimension(this_gf) * scale
    t = np.asarray(r)[:6]
    t = [0.0, 1.0 / SCALE, -1.0 / SCALE, 0.0, *t[[2, 5]]]
    return r, t, s[[1, 0]].astype(int)


def get_segment(line, distance=50.0):
    r = get_coordinates(line.segmentize(distance))
    r = np.stack([gp.points_from_xy(*r[:-1].T), gp.points_from_xy(*r[1:].T)])
    return gp.GeoSeries(pd.DataFrame(r.T).apply(LineString, axis=1), crs=CRS).values


set_precision_pointone = partial(set_precision, grid_size=0.1)


def get_base_nx(filepath):
    r = gp.read_file(filepath).to_crs(CRS)
    r["geometry"] = r["geometry"].map(set_precision_pointone)
    return r


def main():
    log("start")
    base_nx = get_base_nx("data/rnet_princes_street.geojson")
    base_nx.to_file(OUTPATH, layer="input")
    base_nx = base_nx.simplify(tolerance=2.0).to_frame("geometry")
    base_nx.to_file(OUTPATH, layer="clean")
    get_segment_five = partial(get_segment, distance=5.0)
    nx_segment = base_nx["geometry"].map(get_segment_five).explode()
    nx_segment = gp.GeoSeries(nx_segment, crs=CRS).buffer(BUFFER, join_style="mitre")
    # nx_segment.to_file(OUTPATH, layer="buffer")
    nx_union = unary_union(nx_segment)
    try:
        nx_geometry = gp.GeoSeries(nx_union.geoms, crs=CRS)
    except AttributeError:
        nx_geometry = gp.GeoSeries(nx_union, crs=CRS)
    # ux_geometry.to_frame("geometry").to_file(OUTPATH, layer="ux_union")
    r_matrix, s_matrix, out_shape = get_affine_transform(nx_geometry, SCALE)
    set_shapely_transform = partial(affine_transform, matrix=s_matrix)
    raster_im = rif.rasterize(
        nx_geometry.values, transform=r_matrix, out_shape=out_shape, all_touched=True
    )
    raster_im = remove_small_holes(raster_im, 16).astype(np.uint8)
    skeleton_im = skeletonize(raster_im).astype(np.uint8)
    nx_skeleton = np.stack(np.where(skeleton_im == 1)) + 0.5
    nx_point = gp.GeoSeries(map(Point, nx_skeleton.T), crs=CRS)
    nx_point = nx_point.map(set_shapely_transform).set_crs(CRS)
    # x.to_file(OUTPATH, layer="points")
    nx_buffer = nx_point.buffer(1.0 / SCALE, cap_style="square", mitre_limit=1.0 / SCALE)
    # y = y.map(set_affine_image).set_crs(CRS)
    # y.to_file(OUTPATH, layer="square")
    ix = nx_point.sindex.query(nx_buffer, predicate="covers").T
    ix.sort()
    link = pd.DataFrame(ix).drop_duplicates()
    link = link[link[0] != link[1]]
    link = np.stack([nx_point[link[0].values], nx_point[link[1].values]]).T
    line = gp.GeoSeries(map(LineString, link), crs=CRS)
    # line.to_file(OUTPATH, layer="network1")
    line = gp.GeoSeries(line_merge(MultiLineString(line.values)).geoms, crs=CRS)
    line = line.to_frame("geometry")
    line["length"] = line.length
    # line.to_file(OUTPATH, layer="network2")
    ix = (line["length"] > 1.0 / SCALE) & (line["length"] < 2.0 / SCALE)
    simple_line = line.loc[~ix, "geometry"]
    simple_line = gp.GeoSeries(
        line_merge(MultiLineString(simple_line.values)).geoms, crs=CRS
    )
    # simple_line.to_file(OUTPATH, layer="network3")
    simple_line = simplify(simple_line.copy(), tolerance=2.0).set_crs(CRS)
    simple_line.to_file(OUTPATH, layer="simple")
    log("stop")


if __name__ == "__main__":
    main()
