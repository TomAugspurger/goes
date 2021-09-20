from dataclasses import dataclass
import logging
from typing import Any, Dict, List

from h5py import File
from pyproj.crs import ProjectedCRS, GeographicCRS
from pyproj.crs.datum import CustomDatum, CustomEllipsoid
from pyproj.crs.coordinate_operation import GeostationarySatelliteConversion
from shapely.geometry import mapping, Polygon, box

from stactools.core.projection import reproject_geom
from stactools.goes.attributes import GlobalAttributes
from stactools.goes.enums import ImageType
from stactools.goes.file_name import ABIL2FileName

GOES_ELLIPSOID = CustomEllipsoid.from_name("GRS80")

logger = logging.getLogger(__name__)


@dataclass
class DatasetGeometry:
    """The projection and geometry information for a GOES netcdf dataset.

    Projection stuff built with help from
    https://github.com/OSGeo/gdal/blob/95e35bd1c40ec6ce33341ed6390cce955048067f/gdal/frmts/netcdf/netcdfdataset.cpp
    """
    projection_wkt2: str
    projection_shape: List[int]
    projection_transform: List[float]
    projection_bbox: List[float]
    bbox: List[float]
    footprint: Dict[str, Any]

    @classmethod
    def from_nc(cls, nc: File, image_type: ImageType) -> "DatasetGeometry":
        projection = nc["goes_imager_projection"]
        sweep_angle_axis = projection.attrs["sweep_angle_axis"].decode("utf-8")
        satellite_height = projection.attrs["perspective_point_height"][
            0].item()
        latitude_natural_origin = projection.attrs[
            "latitude_of_projection_origin"][0].item()
        longitude_natural_origin = projection.attrs[
            "longitude_of_projection_origin"][0].item()
        extent = nc["geospatial_lat_lon_extent"]
        xmin = extent.attrs["geospatial_westbound_longitude"][0].item()
        ymin = extent.attrs["geospatial_southbound_latitude"][0].item()
        xmax = extent.attrs["geospatial_eastbound_longitude"][0].item()
        ymax = extent.attrs["geospatial_northbound_latitude"][0].item()
        rowcount = len(nc["x"][:])
        colcount = len(nc["y"][:])
        x = nc["x"][:].tolist()
        x_scale = nc["x"].attrs["scale_factor"][0].item()
        x_offset = nc["x"].attrs["add_offset"][0].item()
        y = nc["y"][:].tolist()
        y_scale = nc["y"].attrs["scale_factor"][0].item()
        y_offset = nc["y"].attrs["add_offset"][0].item()

        # we let GRS80 and WGS84 be ~the same for these purposes, since we're
        # not looking for survey-level precision in these bounds
        bbox = [xmin, ymin, xmax, ymax]

        datum = CustomDatum(ellipsoid=GOES_ELLIPSOID)
        conversion = GeostationarySatelliteConversion(
            sweep_angle_axis, satellite_height, latitude_natural_origin,
            longitude_natural_origin)
        crs = ProjectedCRS(conversion=conversion,
                           geodetic_crs=GeographicCRS(datum=datum))

        projection_wkt2 = crs.to_wkt()
        projection_shape = [rowcount, colcount]

        x_bounds = [(x_scale * x + x_offset) * satellite_height
                    for x in [x[0], x[-1]]]
        y_bounds = [(y_scale * y + y_offset) * satellite_height
                    for y in [y[0], y[-1]]]
        xres = (x_bounds[1] - x_bounds[0]) / (rowcount - 1)
        yres = (y_bounds[1] - y_bounds[0]) / (colcount - 1)

        projection_transform = [
            xres, 0, x_bounds[0] - xres / 2, 0, yres, y_bounds[0] - yres / 2,
            0, 0, 1
        ]
        projection_bbox = [x_bounds[0], y_bounds[0], x_bounds[1], y_bounds[1]]

        if image_type != ImageType.FULL_DISK:
            projection_geometry = Polygon([(x_bounds[0], y_bounds[0]),
                                           (x_bounds[0], y_bounds[1]),
                                           (x_bounds[1], y_bounds[1]),
                                           (x_bounds[1], y_bounds[0])])

            geometry = reproject_geom(crs, "EPSG:4326",
                                      mapping(projection_geometry))
        else:
            # Full disk images don't map to espg:4326 well
            # Just use the bbox
            # https://github.com/stactools-packages/goes/issues/4
            geometry = mapping(box(*bbox))

        return DatasetGeometry(projection_wkt2=projection_wkt2,
                               projection_shape=projection_shape,
                               projection_transform=projection_transform,
                               projection_bbox=projection_bbox,
                               bbox=bbox,
                               footprint=geometry)


@dataclass
class Dataset:
    """A GOES netcdf dataset."""

    file_name: ABIL2FileName
    global_attributes: GlobalAttributes
    geometry: DatasetGeometry
    asset_variables: List[str]
    """Keys are variable names, values are long description.

    Only captures variables that are images."""
    @classmethod
    def from_nc(cls, file_name: ABIL2FileName, nc: File) -> "Dataset":
        global_attributes = GlobalAttributes.from_nc(nc)
        geometry = DatasetGeometry.from_nc(nc, file_name.image_type)

        asset_variables = [key for key in nc.keys() if len(nc[key].shape) == 2]

        return Dataset(file_name=file_name,
                       global_attributes=global_attributes,
                       geometry=geometry,
                       asset_variables=asset_variables)
