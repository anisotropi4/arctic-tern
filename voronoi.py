#!/usr/bin/env python3
"""simplify.py: simplify GeoJSON network to GeoPKG layers using Voronoi polygons"""

import argparse
import datetime as dt
from functools import partial

import geopandas as gp
import numpy as np
import pandas as pd
from pyogrio import read_dataframe, write_dataframe
from shapely import box, get_coordinates, line_merge, set_precision, unary_union
from shapely.geometry import LineString, MultiLineString, MultiPoint, Point
from shapely.ops import voronoi_diagram

pd.set_option("display.max_columns", None)
START = dt.datetime.now()
CRS = "EPSG:27700"

set_precision_pointone = partial(set_precision, grid_size=0.1)


def combine_line(line):
    """combine_line: return LineString GeoSeries combining lines with intersecting endpoints

    args:
      line: mixed LineString GeoSeries

    returns:
      join LineString GeoSeries

    """
    r = MultiLineString(line.values)
    return gp.GeoSeries(line_merge(r).geoms, crs=CRS)


def get_base_geojson(filepath):
    """get_base_nx: return GeoDataFrame at 0.1m precision from GeoJSON

    args:
      filepath: GeoJSON path

    returns:
      GeoDataFrame at 0.1m precision

    """
    r = read_dataframe(filepath).to_crs(CRS)
    r["geometry"] = r["geometry"].map(set_precision_pointone)
    return r


def get_end(geometry):
    """get_end: return numpy array of geometry LineString end-points

    args:
      geometry: geometry LineString

    returns:
      end-point numpy arrays

    """
    r = get_coordinates(geometry)
    return np.vstack((r[0, :], r[-1, :]))


def get_geometry_buffer(this_gf, radius=8.0):
    """get_geometry_buffer: return radius buffered GeoDataFrame

    args:
      this_gf: GeoDataFrame to
      radius: (default value = 8.0)

    returns:
      buffered GeoSeries geometry

    """
    r = gp.GeoSeries(this_gf, crs=CRS).buffer(radius, join_style="mitre")
    union = unary_union(r)
    try:
        r = gp.GeoSeries(union.geoms, crs=CRS)
    except AttributeError:
        r = gp.GeoSeries(union, crs=CRS)
    return r


def get_linestring(line):
    """get_linestring: return LineString GeoSeries from line coordinates

    args:
      line:

    returns:
       LineString GeoSeries
    """
    r = get_coordinates(line)
    r = np.stack([gp.points_from_xy(*r[:-1].T), gp.points_from_xy(*r[1:].T)])
    return gp.GeoSeries(pd.DataFrame(r.T).apply(LineString, axis=1), crs=CRS).values


def get_nx(line):
    """get_nx: return primal edge network from LineString GeoDataFrame

    args:
      line: LineString GeoDataFrame

    returns:
      edge GeoDataFrames

    """
    r = line.map(get_end)
    edge = gp.GeoSeries(r.map(LineString), crs=CRS)
    r = np.vstack(r.to_numpy())
    r = gp.GeoSeries(map(Point, r)).to_frame("geometry")
    r = r.groupby(r.columns.to_list(), as_index=False).size()
    return edge


def get_segment(line, distance=50.0):
    """get_segment: segment LineString GeoSeries into distance length segments

    args:
      line: GeoSeries LineString
      length: segmentation distance (default value = 50.0)

    returns:
      GeoSeries of LineStrings of up to length distance

    """
    return get_linestring(line.segmentize(distance))


def get_source_target(line):
    """get_source_target: return edge and node GeoDataFrames from LineString with unique
    node Point and edge source and target

    args:
      line: LineString GeoDataFrame

    returns:
      edge, node: GeoDataFrames

    """
    edge = line.copy()
    r = edge["geometry"].map(get_end)
    r = np.stack(r)
    node = gp.GeoSeries(map(Point, r.reshape(-1, 2)), crs=CRS).to_frame("geometry")
    count = node.groupby("geometry").size().rename("count")
    node = node.drop_duplicates("geometry").set_index("geometry", drop=False)
    node = node.join(count).reset_index(drop=True).reset_index(names="node")
    ix = node.set_index("geometry")["node"]
    edge = edge.reset_index(names="edge")
    edge["source"] = ix.loc[map(Point, r[:, 0])].values
    edge["target"] = ix.loc[map(Point, r[:, 1])].values
    return edge, node


def log(this_string):
    """log: print timestamp appended to 'this_string'

      this_string: text to print

    returns:
      None

    """
    now = dt.datetime.now() - START
    print(this_string + f"\t{now}")


def get_segment_nx(line, scale):
    """get_segment_nx: segment line into sections, no more than scale long

    args:
      line:  line to segment
      scale: length to segment line

    returns:
      segmented LineStrings

    """
    set_segment = partial(get_segment, distance=scale)
    r = line.map(set_segment).explode().rename("geometry")
    return gp.GeoDataFrame(r, crs=CRS)


def get_geometry_line(this_buffer):
    """get_geometry_line: returns LineString boundary from geometry

    args:
      this_buffer: geometry to find LineString

    returns:
       simplified LineString boundary
    """
    r = this_buffer.boundary.explode(index_parts=False).reset_index(drop=True)
    return gp.GeoSeries(r.simplify(tolerance=0.5), crs=CRS)


def get_voronoi(this_buffer, tolerance, scale):
    """voronoi_nx: return Voronoi polygon using segmented points from the buffer

    args:
      this_buffer: segmented
      tolerance:   distance to snap input vertices
      scale:       distance between segment boundary points

    returns:
      Voronoi polygon
    """
    segment = get_segment_nx(this_buffer, scale).reset_index(drop=True)
    point = segment.loc[:, "geometry"].map(get_coordinates).explode()
    point = MultiPoint(point[::2].map(Point).values)
    boundary = box(*point.bounds)
    r = voronoi_diagram(point, envelope=boundary, tolerance=tolerance, edges=True)
    r = gp.GeoSeries(map(set_precision_pointone, r.geoms), crs=CRS)
    r = r.explode(index_parts=False).clip(boundary)
    ix = ~r.is_empty & (r.type == "LineString")
    return r[ix].reset_index(drop=True)


def filter_distance(line, boundary, offset):
    """filter_distance: filter line closer than distance offset from boundary

    args:
      line:     LineStrings to simplify
      boundary: boundary LineString
      offset:

    returns:
      simplified LineStrings
    """
    edge, _ = get_source_target(line.to_frame("geometry"))
    (ix, _), distance = boundary.sindex.nearest(edge["geometry"], return_distance=True)
    _, ix = np.unique(ix, return_index=True)
    ix = distance[ix] > offset
    return combine_line(edge.loc[ix, "geometry"]).simplify(1.0)


def filter_buffer(line, geometry):
    """filter_buffer: filter keeping lines within boundary Polygon

    args:
      line:     LineStrings to simplify
      geometry: boundary Polygon

    returns:
      filtered LineStrings
    """
    (_, ix) = line.sindex.query(geometry, predicate="contains_properly")
    return combine_line(line.loc[ix]).simplify(1.0)


def set_geometry(line, square):
    """set_geometry: return LineString simplified by combining overlapping end-points

    args:
      line:     LineStrings to simplify
      square:   overlapping squares

    returns:
      simplified LineStrings

    """
    r = line.reset_index(drop=True)
    centroid = square.centroid.map(set_precision_pointone).set_crs(CRS)
    edge, node = get_source_target(r)
    ix = node["geometry"].sindex.query(square, predicate="contains_properly")
    node.loc[ix[1], "geometry"] = centroid[ix[0]].values
    source = node.loc[edge["source"], "geometry"].values
    target = node.loc[edge["target"], "geometry"].values
    r = np.stack([source, target]).T
    return gp.GeoSeries(map(LineString, r), crs=CRS)


def get_voronoi_line(voronoi, boundary, geometry, buffer_size):
    """get_voronoi_line: returns cleaned simplified line by filtering Voronoi lines by distance,
    contained within network buffer Polygons, and combining overlapping end-points

    args:
      voronoi:     Voronoi LineString
      boundary:    network buffer LineString
      geometry:    network buffer Polygon
      buffer_size: network buffer distance [m]

    returns:
      simplified simplified network line

    """
    offset = buffer_size / 2.0
    r = filter_distance(voronoi, boundary, offset)
    r = filter_buffer(r, geometry)
    edge, node = get_source_target(r.to_frame("geometry"))
    ix = node["count"] < 4
    square = node[ix].buffer(offset, cap_style="square", mitre_limit=offset)
    square = gp.GeoSeries(unary_union(square.values).geoms, crs=CRS)
    r = edge["geometry"].map(get_linestring).explode().to_frame("geometry")
    r = set_geometry(r, square)
    return combine_line(r)


def main(inpath, outpath, parameter):
    """main: load GeoJSON file, use Voronoi polygons to simplify network, and output
    the input, simplified and primal network as GeoPKG layers

    args:
      inpath:      filepath to input GeoJSON file
      outpath:     filepath to output GeoPKG file
      parameter:
        simplify:    simplify tolerance [m]
        buffer:      network buffer distance [m]
        scale:       scale distance between edge point to form Voronoi
        tolerance:   snap Voronoi vertices together if their distance is less than this

    returns:
      None

    """
    log("start\t")
    base_nx = get_base_geojson(inpath)
    log("read geojson")
    write_dataframe(base_nx, outpath, layer="input")
    log("process\t")
    radius = parameter["buffer"]
    nx_geometry = get_geometry_buffer(base_nx["geometry"], radius=radius)
    nx_boundary = get_geometry_line(nx_geometry)
    nx_voronoi = get_voronoi(nx_boundary, parameter["tolerance"], parameter["scale"])
    log("dewhisker")
    nx_line = get_voronoi_line(nx_voronoi, nx_boundary, nx_geometry, radius)
    log("write simple")
    simplify = parameter["simplify"]
    if simplify > 0.0:
        nx_line = nx_line.simplify(simplify)
    write_dataframe(nx_line.to_frame("geometry"), outpath, layer="line")
    nx_edge = get_nx(nx_line)
    log("write primal")
    write_dataframe(nx_edge.to_frame("geometry"), outpath, layer="primal")
    log("stop\t")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="GeoJSON network Voronoi simplification"
    )
    parser.add_argument("inpath", type=str, help="GeoJSON filepath to simplify")
    parser.add_argument(
        "outpath",
        nargs="?",
        type=str,
        help="GeoGPKG output path",
        default="output.gpkg",
    )
    parser.add_argument("--simplify", help="tolerance [m]", type=float, default=0.0)
    parser.add_argument("--scale", help="Voronoi scale", type=float, default=5.0)
    parser.add_argument("--buffer", help="line buffer [m]", type=float, default=8.0)
    parser.add_argument(
        "--tolerance", help="Voronoi snap distance", type=float, default=1.0
    )
    args = parser.parse_args()
    main_parameter = {
        "simplify": args.simplify,
        "buffer": args.buffer,
        "scale": args.scale,
        "tolerance": args.tolerance,
    }
    main(
        args.inpath,
        args.outpath,
        main_parameter,
    )
