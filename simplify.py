#!/usr/bin/env python

import datetime as dt
import warnings
from functools import partial

import geopandas as gp
import networkx as nx
import numpy as np
import pandas as pd
import rasterio as rio
import rasterio.features as rif
from pyogrio import write_dataframe
from shapely import get_coordinates, line_merge, set_precision, unary_union
from shapely.affinity import affine_transform
from shapely.geometry import LineString, MultiLineString, MultiPoint, Point
from skimage.morphology import remove_small_holes, skeletonize

pd.set_option("display.max_columns", None)

START = dt.datetime.now()

OUTPATH = "dx3.gpkg"
CRS = "EPSG:27700"

SCALE = 8.0
# SCALE = 0.5
# SCALE = 1.0
BUFFER = 8.0


def log(this_string):
    """print timestamp appended to 'this_string'
    :param this_string:
    """
    now = dt.datetime.now() - START
    print(this_string + f"\t{now}")


def get_dimension(bound, scale):
    r = np.diff(bound.reshape(-1, 2), axis=0)
    r = np.ceil(r.reshape(-1))
    return (r[[1, 0]] * scale).astype(int)


def get_affine_transform(this_gf, scale=1.0):
    TRANSFORM_ONE = np.asarray([0.0, 1.0, -1.0, 0.0, 1.0, 1.0])
    bound = this_gf.total_bounds
    s = TRANSFORM_ONE / scale
    s[[4, 5]] = bound[[0, 3]]
    r = s[[1, 0, 4, 3, 2, 5]]
    r = rio.Affine(*r)
    return r, s, get_dimension(bound, scale)


def get_segment(line, distance=50.0):
    r = get_coordinates(line.segmentize(distance))
    r = np.stack([gp.points_from_xy(*r[:-1].T), gp.points_from_xy(*r[1:].T)])
    return gp.GeoSeries(pd.DataFrame(r.T).apply(LineString, axis=1), crs=CRS).values


set_precision_pointone = partial(set_precision, grid_size=0.1)


def get_base_nx(filepath):
    r = gp.read_file(filepath).to_crs(CRS)
    r["geometry"] = r["geometry"].map(set_precision_pointone)
    return r


def get_geometry(this_frame, segment=5.0, radius=BUFFER):
    set_segment = partial(get_segment, distance=segment)
    r = this_frame.map(set_segment).explode()
    r = gp.GeoSeries(r, crs=CRS).buffer(radius, join_style="mitre")
    union = unary_union(r)
    try:
        r = gp.GeoSeries(union.geoms, crs=CRS)
    except AttributeError:
        r = gp.GeoSeries(union, crs=CRS)
    return r


def get_raster_point(raster):
    r = np.stack(np.where(raster == 1))
    return gp.GeoSeries(map(Point, r.T), crs=CRS)


def nx_out(this_gf, transform, layer):
    r = this_gf.copy()
    try:
        r = r.to_frame("geometry")
    except AttributeError:
        pass
    geometry = r["geometry"].map(transform)
    r["geometry"] = geometry
    write_dataframe(r, OUTPATH, layer=layer)


def combine_line(line):
    r = MultiLineString(line.values)
    return gp.GeoSeries(line_merge(r).geoms, crs=CRS)


def get_end(geometry):
    r = get_coordinates(geometry)
    return np.vstack((r[0, :], r[-1, :]))


def get_source_target(this_gf):
    edge = this_gf.copy()
    r = edge["geometry"].map(get_end)
    r = np.stack(r)
    node = gp.GeoSeries(map(Point, r.reshape(-1, 2)), crs=CRS).drop_duplicates()
    node = node.reset_index(drop=True).to_frame("geometry")
    node = node.reset_index(names="node")
    ix = node.set_index("geometry")
    edge["source"] = ix.loc[map(Point, r[:, 0])].values
    edge["target"] = ix.loc[map(Point, r[:, 1])].values
    return edge, node


def get_nx(line):
    r = line.map(get_end)
    edge = gp.GeoSeries(r.map(LineString), crs=CRS)
    r = np.vstack(r.to_numpy())
    r = gp.GeoSeries(map(Point, r)).to_frame("geometry")
    r = r.groupby(r.columns.to_list(), as_index=False).size()
    node = gp.GeoDataFrame(r, crs=CRS)
    return edge, node


def get_skeleton(geometry, transform, shape):
    r = rif.rasterize(geometry.values, transform=transform, out_shape=shape)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        # parent, traverse = max_tree(invert(r))
        r = remove_small_holes(r, 4).astype(np.uint8)
    r = skeletonize(r).astype(np.uint8)
    return r


def get_connected_class(edge_list):
    nx_graph = nx.from_pandas_edgelist(edge_list)
    connected = nx.connected_components(nx_graph)
    r = {k: i for i, j in enumerate(connected) for k in j}
    return pd.Series(r, name="class")


def get_centre_edge(node):
    centre = node[["geometry", "class"]].groupby("class").aggregate(tuple)
    centre = gp.GeoSeries(centre["geometry"].map(MultiPoint), crs=CRS).centroid
    centre = centre.rename("target")
    geometry = node[["class", "geometry"]].set_index("class").join(centre)
    geometry = geometry.apply(LineString, axis=1)
    r = node.rename(columns={"node": "source"}).copy()
    r["geometry"] = geometry.values
    return r


def debug_raster_line(point, transform):
    square = point.buffer(1, cap_style="square", mitre_limit=1)
    ix = point.sindex.query(square, predicate="covers").T
    ix.sort()
    s = pd.DataFrame(ix).drop_duplicates()
    s = s[s[0] != s[1]]
    s = np.stack([point[s[0].values], point[s[1].values]]).T
    r = gp.GeoSeries(map(LineString, s), crs=CRS)
    edge, node = get_source_target(combine_line(r).to_frame("geometry"))
    nx_out(edge, transform, "mx_edge")
    ix = edge.length < 2.0
    connected = get_connected_class(edge.loc[ix, ["source", "target"]])
    mx_node = node.loc[connected.index].join(connected).sort_index()
    mx_edge = get_centre_edge(mx_node)
    mx_out = combine_line(pd.concat([mx_edge["geometry"], edge.loc[~ix, "geometry"]]))
    return mx_out[mx_out.length > 2.0]


def get_raster_line(point):
    square = point.buffer(1, cap_style="square", mitre_limit=1)
    ix = point.sindex.query(square, predicate="covers").T
    ix.sort()
    s = pd.DataFrame(ix).drop_duplicates()
    s = s[s[0] != s[1]]
    s = np.stack([point[s[0].values], point[s[1].values]]).T
    r = gp.GeoSeries(map(LineString, s), crs=CRS)
    edge, node = get_source_target(combine_line(r).to_frame("geometry"))
    ix = edge.length < 2.0
    connected = get_connected_class(edge.loc[ix, ["source", "target"]])
    mx_node = node.loc[connected.index].join(connected).sort_index()
    mx_edge = get_centre_edge(mx_node)
    mx_out = combine_line(pd.concat([mx_edge["geometry"], edge.loc[~ix, "geometry"]]))
    return mx_out[mx_out.length > 2.0]


def main():
    log("start")
    base_nx = get_base_nx("data/rnet_princes_street.geojson")
    base_nx.to_file(OUTPATH, layer="input")
    nx_geometry = get_geometry(base_nx["geometry"])
    r_matrix, s_matrix, out_shape = get_affine_transform(nx_geometry, SCALE)
    shapely_transform = partial(affine_transform, matrix=s_matrix)
    skeleton_im = get_skeleton(nx_geometry, r_matrix, out_shape)
    nx_point = get_raster_point(skeleton_im)
    #nx_line = get_raster_line(nx_point)
    nx_line = debug_raster_line(nx_point, shapely_transform)
    nx_out(nx_line, shapely_transform, "line")
    nx_edge, nx_node = get_nx(nx_line)
    nx_out(nx_edge, shapely_transform, "sx_edge")
    nx_out(nx_node, shapely_transform, "sx_node")
    log("stop")


if __name__ == "__main__":
    main()
