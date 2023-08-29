# artic-tern
GeoJSON network simplification using raster image skeletonization and Voronoi polygons

The load GeoJSON file, use Voronoi polygons to simplify network, and output GeoPKG layers corresponding to the input, simplified and primal network

The sample data set is of Queenstreet in Edinburgh kindly shared by Robin Lovelace

## Skeletonization
This creates a simplified network by applying skeletonization to a buffered raster array

## Voronoi
This creates a simplified network by creating set of Voronoi polygons from points on the buffer

## Running the code

To run the code in this repo, first download a dataset you would like to simplify.
There is a test dataset in data/rnet_princes_street.geojson

Then run the following command:

```sh
python3 skeletonize.py data/rnet_princes_street.geojson
```

## Notes
Both are the skeletonization and Voronoi approach are generic approaches, with the following known issues:

* This does not maintain a link between attributes and the simplified network
* This does not identify a subset of edges that need simplification
* The lines are a bit wobbly