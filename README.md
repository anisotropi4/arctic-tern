# artic-tern
GeoJSON network simplification using raster image skeletonization and Voronoi polygons

The load GeoJSON file, use Voronoi polygons to simplify network, and output GeoPKG layers corresponding to the input, simplified and primal network

The sample data set is of Queenstreet in Edinburgh kindly shared by Robin Lovelace

## Simple operation
The `run.sh` script setups a python virtual environment and executes the script against a data file in the `data` directory

    $ ./run.sh

The `run.sh` script optionally takes a filename and file-extension. To simplify a file, say `somewhere.geojson` and output to `GeoPKG` files `sk-thing.gpkg` and `vr-thing.gpkg`
    
    $ ./run.sh somewhere.geojon thing

## Skeletonization
In an activated virtual environment, the following creates a simplified network by applying skeletonization to a buffered raster array
    
    (venv) $ ./skeletonize.py data/rnet_princes_street.geojson
   
## Voronoi
In an activated virtual environment, the following creates a simplified network by creating set of Voronoi polygons from points on the buffer
   
    (venv) $ ./voronoi.py data/rnet_princes_street.geojson

## Setup
The script assumes a working command line environment with an accessible working python3 environment, with an optional working `ogr2ogr` executable

### Simple setup
The `./run.sh` script will create a python virtual environment with dependencies in the `venv` directory, activate this environment and create test `GeoPKG` and, if `ogr2ogr` is installed, `GeoJSON` files

### Manual virtual environment setup
To replicate the creation and activation of a python virtual environment in the `run.sh` script, execute the following commands

     $ python3 -m venv venv
     $ source venv/bin/activate
     $ pip install --upgrade pip
     $ pip install --upgrade wheel
     $ pip install --upgrade -r requirements.txt

Where the module dependencies are contained in the `requirements.txt`

### Activate virtual enviroment

Once installed to activate a virtual environment

    $ source venv/bin/activate

## Notes
Both are the skeletonization and Voronoi approach are generic approaches, with the following known issues:

* This does not maintain a link between attributes and the simplified network
* This does not identify a subset of edges that need simplification
* The lines are a bit wobbly
