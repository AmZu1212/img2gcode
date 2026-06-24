# from xml.dom import minidom

# doc = minidom.parse("test.svg")  # parseString also exists
# path_strings = [path.getAttribute('d') for path
#                 in doc.getElementsByTagName('path')]
# doc.unlink()

# path_string = " ".join(path_strings)

# print(path_string)
# import matplotlib.pyplot as plt
# import matplotlib.lines as mlines
# import matplotlib.colors as mcolors
# from matplotlib.animation import FuncAnimation
from svgpathtools import svg2paths2, wsvg, Line, Path
from svg.path import parse_path
import numpy as np
from tqdm import tqdm
from simplification.cutil import (
    simplify_coords,
    simplify_coords_idx,
    simplify_coords_vw,
    simplify_coords_vw_idx,
    simplify_coords_vwp,
)
from loguru import logger as log
import click
from PIL import Image, ImageDraw
from datetime import datetime

import math
import random
import hashlib
import ntpath
import os
import subprocess
import sys
from shutil import copyfile, which


def dist2(p1, p2):
    return (p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2


def fuse(points, d):
    ret = []
    d2 = d * d
    n = len(points)
    taken = [False] * n
    for i in range(n):
        if not taken[i]:
            count = 1
            point = [points[i][0], points[i][1]]
            taken[i] = True
            for j in range(i + 1, n):
                if dist2(points[i], points[j]) < d2:
                    point[0] += points[j][0]
                    point[1] += points[j][1]
                    count += 1
                    taken[j] = True
            point[0] /= count
            point[1] /= count
            ret.append((point[0], point[1]))
    return ret


def fuse_linear(points, d):
    ret = []
    deleted = {}
    for _, p1 in enumerate(points):
        has_close_point = False
        for j, p2 in enumerate(ret):
            if dist2(p1, p2) < d:
                has_close_point = True
                break
        if not has_close_point:
            ret.append(p1)
    return ret


def cubic_bezier_sample(start, control1, control2, end):
    inputs = np.array([start, control1, control2, end])
    cubic_bezier_matrix = np.array(
        [[-1, 3, -3, 1], [3, -6, 3, 0], [-3, 3, 0, 0], [1, 0, 0, 0]]
    )
    partial = cubic_bezier_matrix.dot(inputs)

    return lambda t: np.array([t ** 3, t ** 2, t, 1]).dot(partial)


def fmt_coord(value):
    text = f"{value:.3f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def sample_svg_paths(attributes, bezier_segments=24):
    bezier_segments = max(2, int(bezier_segments))
    new_paths = []
    for attribute in attributes:
        sampled_path = []
        path = parse_path(attribute["d"])
        for ele in path:
            if "CubicBezier" in str(ele):
                curve = cubic_bezier_sample(
                    ele.start, ele.control1, ele.control2, ele.end
                )
                points = np.array(
                    [curve(t) for t in np.linspace(0, 1, bezier_segments)]
                )
                for k, _ in enumerate(points):
                    if k == 0:
                        continue
                    sampled_path.append(
                        Line(
                            complex(np.real(points[k - 1]), np.imag(points[k - 1])),
                            complex(np.real(points[k]), np.imag(points[k])),
                        )
                    )
            elif "Line" in str(ele):
                sampled_path.append(Line(ele.start, ele.end))
            elif "Move" in str(ele) or "Close" in str(ele):
                if len(sampled_path) > 0:
                    new_paths.append(sampled_path)
                sampled_path = []
        if len(sampled_path) > 0:
            new_paths.append(sampled_path)
    return new_paths


def lines_to_coords(paths):
    coords_path = []
    for path in paths:
        coords = []
        for j, ele in enumerate(path):
            x1 = float(np.real(ele.start))
            y1 = float(np.imag(ele.start))
            x2 = float(np.real(ele.end))
            y2 = float(np.imag(ele.end))
            if j == 0:
                coords.append([x1, y1])
            coords.append([x2, y2])
        if len(coords) > 0:
            coords_path.append(coords)
    return coords_path


def get_coords_bounds(coords_path):
    xs = []
    ys = []
    for coords in coords_path:
        for x, y in coords:
            xs.append(x)
            ys.append(y)
    if not xs:
        return [0.0, 0.0, 0.0, 0.0]
    return [min(xs), max(xs), min(ys), max(ys)]


def fit_coords_to_drawing_area(coords_path, drawing_area):
    if not coords_path:
        return coords_path

    minx, maxx, miny, maxy = drawing_area
    src_min_x, src_max_x, src_min_y, src_max_y = get_coords_bounds(coords_path)
    src_width = src_max_x - src_min_x
    src_height = src_max_y - src_min_y
    dst_width = maxx - minx
    dst_height = maxy - miny

    if src_width == 0 and src_height == 0:
        center_x = minx + dst_width / 2.0
        center_y = miny + dst_height / 2.0
        return [[[center_x, center_y] for _ in coords] for coords in coords_path]

    if src_width == 0:
        scale = dst_height / src_height
    elif src_height == 0:
        scale = dst_width / src_width
    else:
        scale = min(dst_width / src_width, dst_height / src_height)

    scaled_width = src_width * scale
    scaled_height = src_height * scale
    offset_x = minx + (dst_width - scaled_width) / 2.0 - src_min_x * scale
    offset_y = miny + (dst_height - scaled_height) / 2.0 - src_min_y * scale

    fitted = []
    for coords in coords_path:
        fitted_coords = []
        for x, y in coords:
            fitted_x = x * scale + offset_x
            fitted_y = y * scale + offset_y
            fitted_x = min(max(fitted_x, minx), maxx)
            fitted_y = min(max(fitted_y, miny), maxy)
            fitted_coords.append([fitted_x, fitted_y])
        fitted.append(fitted_coords)
    return fitted


def run_command(args):
    log.debug("running {}", " ".join(str(arg) for arg in args))
    subprocess.run([str(arg) for arg in args], check=True)


def filter_short_segments(coords, min_segment_length=0.0):
    if len(coords) <= 2 or min_segment_length <= 0:
        return coords

    min_dist2 = min_segment_length * min_segment_length
    filtered = [coords[0]]
    for coord in coords[1:-1]:
        if dist2(coord, filtered[-1]) >= min_dist2:
            filtered.append(coord)
    if dist2(coords[-1], filtered[-1]) > 0:
        filtered.append(coords[-1])
    elif len(filtered) == 1:
        filtered.append(coords[-1])
    return filtered


def write_paths_to_gcode(
    fname,
    paths,
    drawing_area,
    feed_rate=5400,
    pen_rate=500,
    pen_down_z=0.0,
    pen_up_z=5.0,
):
    bed_width = drawing_area[1] - drawing_area[0]
    bed_height = drawing_area[3] - drawing_area[2]
    timestamp = datetime.now().strftime("%d/%m/%Y, %H:%M:%S")
    gcode_lines = [
        "; GCODE GENERATED BY IMAGE-TO-GCODE CONVERTER",
        f"; DATE: {timestamp}",
        f"; BED SIZE: {fmt_coord(bed_width)}x{fmt_coord(bed_height)}mm",
        "",
        "G21 ; SET UNITS TO MILLIMETERS",
        "G90 ; ABSOLUTE POSITIONING",
        f"G1 F{int(feed_rate)} ; SET DRAW FEED RATE",
        f"G0 Z{fmt_coord(pen_up_z)} F{int(pen_rate)} ; PEN UP",
        f"G0 X0 Y0 F{int(feed_rate)} ; MOVE TO ORIGIN",
        "",
        "; BEGIN DRAWING",
    ]
    for path in paths:
        if len(path) == 0:
            continue

        start_x = np.real(path[0].start)
        start_y = np.imag(path[0].start)
        gcode_lines.append(
            f"G0 X{fmt_coord(start_x)} Y{fmt_coord(start_y)} F{int(feed_rate)} ; RAPID TO START"
        )
        gcode_lines.append(f"G1 Z{fmt_coord(pen_down_z)} F{int(pen_rate)} ; PEN DOWN")

        for ele in path:
            end_x = np.real(ele.end)
            end_y = np.imag(ele.end)
            gcode_lines.append(
                f"G1 X{fmt_coord(end_x)} Y{fmt_coord(end_y)} F{int(feed_rate)} ; DRAW LINE"
            )

        gcode_lines.append(f"G0 Z{fmt_coord(pen_up_z)} F{int(pen_rate)} ; PEN UP")
        gcode_lines.append("")

    gcode_lines.append(f"G0 Z{fmt_coord(pen_up_z)} F{int(pen_rate)} ; PEN UP")
    gcode_lines.append(f"G0 X0 Y0 F{int(feed_rate)} ; RETURN TO ORIGIN")
    with open(fname, "w") as f:
        f.write("\n".join(gcode_lines).strip() + "\n")


def merge_similar(paths, threshold_dist):
    if len(paths) <= 1:
        return paths
    # merge similar paths
    final_paths = []
    for i, coords in enumerate(paths):
        if i == 0:
            final_paths.append(coords)
            continue
        d = dist2(
            coords[0],
            final_paths[len(final_paths) - 1][
                len(final_paths[len(final_paths) - 1]) - 1
            ],
        )
        if d < threshold_dist:
            final_paths[len(final_paths) - 1] += coords
        else:
            final_paths.append(coords)

    return final_paths


def minimize_moves(paths, junction_distance=400):
    if len(paths) <= 1:
        return paths
    endpoints = []
    for _, coords in enumerate(paths):
        if len(coords) == 0:
            continue
        endpoints.append(coords[0])
        if len(coords) > 1:
            endpoints.append(coords[len(coords) - 1])
        else:
            endpoints.append(coords[0])

    paths_split = []
    for _, coords in enumerate(paths):
        path = []
        for _, coord in enumerate(coords):
            isclose = False
            for _, coord2 in enumerate(endpoints):
                if dist2(coord, coord2) < junction_distance:
                    if len(path) > 0:
                        paths_split.append(path)
                    path = []
                    break
            path.append(coord)
        if len(path) > 0:
            paths_split.append(path)

    log.debug(len(paths))
    paths = paths_split.copy()
    log.debug(len(paths))

    tries = int(8000 / len(paths))
    log.debug("minimizing moves for {} tries", tries)

    # greedy algorithm
    # for each path, find which end is closest to any other line
    # and add to either the beginning or the end of the path
    bestonepath = []
    bestonepathscore = 29997000000
    for i in tqdm(range(tries)):
        random.shuffle(paths)

        totaldist = 0
        onepath = []
        paths_finished = {}
        for i, coords in enumerate(paths):
            if len(coords) == 0:
                continue

            if len(onepath) == 0:
                onepath.append(coords)
                paths_finished[i] = {}

            cs = onepath[0][0]
            ce = onepath[len(onepath) - 1][len(onepath[len(onepath) - 1]) - 1]

            minDist = 1000000000
            onepathnext = onepath.copy()
            bestpath = -1
            for j, coords2 in enumerate(paths):
                if j == i or j in paths_finished or len(coords2) == 0:
                    continue
                cs2 = coords2[0]
                ce2 = coords2[len(coords2) - 1]
                d = dist2(cs2, cs)
                if d < minDist:
                    minDist = d
                    bestpath = j
                    coords2copy = coords2.copy()
                    coords2copy.reverse()
                    onepathnext = onepath.copy()
                    onepathnext = [coords2copy] + onepathnext

                d = dist2(ce, cs2)
                if d < minDist:
                    minDist = d
                    bestpath = j
                    onepathnext = onepath.copy()
                    onepathnext = onepathnext + [coords2.copy()]

                d = dist2(ce, ce2)
                if d < minDist:
                    minDist = d
                    bestpath = j
                    onepathnext = onepath.copy()
                    coords2copy = coords2.copy()
                    coords2copy.reverse()
                    onepathnext = onepathnext + [coords2copy]

                d = dist2(cs, ce2)
                if d < minDist:
                    minDist = d
                    bestpath = j
                    onepathnext = onepath.copy()
                    onepathnext = [coords2.copy()] + onepathnext

            onepath = onepathnext.copy()
            paths_finished[bestpath] = {}

        for i, path in enumerate(onepath):
            if i == 0:
                continue
            d = dist2(onepath[i - 1][len(onepath[i - 1]) - 1], onepath[i][0])
            totaldist += math.sqrt(d)
        if len(onepath) == 1:
            totaldist = -1
        if totaldist < bestonepathscore and totaldist > 0:
            bestonepathscore = totaldist
            bestonepath = onepath.copy()
    # maxDist = dist2(
    #     onepath[0][0], onepath[len(onepath) - 1][len(onepath[len(onepath) - 1]) - 1]
    # )
    # minCut = 0
    # for i, path in enumerate(onepath):
    #     if i == 0:
    #         continue
    #     point1 = onepath[i - 1][len(onepath[i - 1]) - 1]
    #     point2 = onepath[i][0]
    #     d = dist2(point1, point2)
    #     if d > maxDist:
    #         minCut = i
    # if minCut > 0:
    #     log.debug("splitting at {}",minCut)
    #     onepath = onepath[minCut:] + onepath[:minCut]
    return bestonepath, paths_split


def write_paths_to_svg(fname, paths, bounds):
    with open(fname, "w") as f:
        f.write(
            f'<?xml version="1.0" standalone="yes"?><svg width="{fmt_coord(bounds[1]-bounds[0])}" height="{fmt_coord(bounds[3]-bounds[2])}" viewBox="{fmt_coord(bounds[0])} {fmt_coord(bounds[2])} {fmt_coord(bounds[1]-bounds[0])} {fmt_coord(bounds[3]-bounds[2])}"><g>'
        )
        for path in paths:
            pathstring = ""
            for j, ele in enumerate(path):
                x1 = np.real(ele.start)
                y1 = np.imag(ele.start)
                x2 = np.real(ele.end)
                y2 = np.imag(ele.end)
                if j == 0:
                    pathstring += f"M {fmt_coord(x1)},{fmt_coord(y1)} "

                if j > 0 or len(path) == 1:
                    pathstring += f"L {fmt_coord(x2)},{fmt_coord(y2)} "
            f.write(
                f'<path d="{pathstring}"'
                + """ fill="none" stroke="#000000" stroke-width="0.777"/>"""
                + "\n"
            )
        f.write("</g></svg>\n")


def coords_to_svg(
    coords_path, simplifylevel=0, minPathLength=0, min_segment_length=0.0
):
    num_coords = 0
    num_coords_simplified = 0
    new_new_paths = []
    for _, coords in enumerate(coords_path):
        simplified = coords
        if simplifylevel > 0:
            log.debug("doing simplification")
            simplified = simplify_coords(simplified, simplifylevel)
        simplified = filter_short_segments(
            simplified, min_segment_length=min_segment_length
        )

        num_coords += len(coords)
        num_coords_simplified += len(simplified)

        new_path = []
        for i, coord in enumerate(simplified):
            if i == 0 and len(simplified) == 1:
                path = Line(
                    complex(simplified[i][0], simplified[i][1]),
                    complex(simplified[i][0], simplified[i][1]),
                )
                new_path.append(path)
            if i == 0:
                continue
            path = Line(
                complex(simplified[i - 1][0], simplified[i - 1][1]),
                complex(simplified[i][0], simplified[i][1]),
            )
            new_path.append(path)
        if len(new_path) > 0 and len(new_path) >= minPathLength:
            new_new_paths.append(new_path)

    log.debug(f"now have {len(new_new_paths)} lines")
    log.debug(f"have {num_coords} coordinates")
    log.debug(f"have {num_coords_simplified} coordinates after simplifying")
    return new_new_paths


def processAutotraceSVG(
    fnamein,
    fnameout,
    drawing_area=[0, 190, 0, 190],
    simplifylevel=1,
    minPathLength=1,
    mergeSize=1,
    minimizeMoves=True,
    junction_distance=400,
    bezier_segments=12,
    min_segment_length=0.2,
):
    if minPathLength < 0:
        minPathLength = 0
    paths, attributes, svg_attributes = svg2paths2(fnamein)
    log.info("have {} paths", len(paths))

    log.debug("converting beziers to lines")

    new_paths = sample_svg_paths(attributes, bezier_segments=bezier_segments)
    coords_path = fit_coords_to_drawing_area(lines_to_coords(new_paths), drawing_area)
    coords_path = [coords for coords in coords_path if len(coords) >= minPathLength]

    write_paths_to_svg(
        "new_paths.svg",
        coords_to_svg(
            coords_path,
            simplifylevel=0,
            minPathLength=0,
            min_segment_length=min_segment_length,
        ),
        drawing_area,
    )

    if minimizeMoves and len(coords_path) > 1:
        log.debug("doing minimization")
        log.debug("coords_path length: {}", len(coords_path))
        write_paths_to_svg(
            "final_unminimized.svg",
            coords_to_svg(
                coords_path,
                simplifylevel=simplifylevel,
                minPathLength=minPathLength,
                min_segment_length=min_segment_length,
            ),
            drawing_area,
        )
        log.debug(junction_distance)
        coords_path, paths_split = minimize_moves(
            coords_path, junction_distance=junction_distance
        )
        write_paths_to_svg(
            "final_unminimized_split.svg",
            coords_to_svg(
                paths_split,
                simplifylevel=simplifylevel,
                minPathLength=minPathLength,
                min_segment_length=min_segment_length,
            ),
            drawing_area,
        )
    log.debug("coords_path length: {}", len(coords_path))

    if mergeSize > 1:
        log.debug("doing merge")
        coords_path = merge_similar(coords_path, mergeSize ** 2)

    new_new_paths = coords_to_svg(
        coords_path,
        simplifylevel=simplifylevel,
        minPathLength=minPathLength,
        min_segment_length=min_segment_length,
    )
    write_paths_to_svg("final.svg", new_new_paths, drawing_area)
    write_paths_to_gcode("image.gcode", new_new_paths, drawing_area)
    return new_new_paths


def processSVG(
    fnamein,
    fnameout,
    simplifylevel=0.25,
    pruneLittle=7,
    drawing_area=[0, 190, 0, 190],
    bezier_segments=12,
    min_segment_length=0.2,
):
    paths, attributes, svg_attributes = svg2paths2(fnamein)
    log.info("have {} paths", len(paths))

    log.debug("converting beziers to lines")

    new_paths = sample_svg_paths(attributes, bezier_segments=bezier_segments)
    coords_path = fit_coords_to_drawing_area(lines_to_coords(new_paths), drawing_area)
    num_coords = 0
    num_coords_simplified = 0
    new_paths_flat = []
    new_new_paths = []
    for coords in coords_path:
        simplified = coords
        if simplifylevel > 0:
            simplified = simplify_coords(simplified, simplifylevel)
        simplified = filter_short_segments(
            simplified, min_segment_length=min_segment_length
        )

        num_coords += len(coords)
        num_coords_simplified += len(simplified)

        new_path = []
        for i, coord in enumerate(simplified):
            if i == 0 and len(simplified) > 0:
                continue
            path = Line(
                complex(simplified[i - 1][0], simplified[i - 1][1]),
                complex(simplified[i][0], simplified[i][1]),
            )
            new_path.append(path)
            new_paths_flat.append(path)
            # new_paths[j][i] = Line(complex(x1,y1),complex(x2,y2))
        new_new_paths.append(new_path)

    log.debug(f"have {num_coords} coordinates")
    log.debug(f"have {num_coords_simplified} coordinates after simplifying")
    write_paths_to_svg(fnameout, new_new_paths, drawing_area)

    log.debug("wrote image to {}", fnameout)

    write_paths_to_gcode("image.gcode", new_new_paths, drawing_area)

    return new_new_paths


def rgb(minimum, maximum, value):
    minimum, maximum = float(minimum), float(maximum)
    ratio = 2 * (value - minimum) / (maximum - minimum)
    b = int(max(0, 255 * (1 - ratio)))
    r = int(max(0, 255 * (ratio - 1)))
    g = 255 - b - r
    return (r, g, b)


def animateProcess(new_paths, bounds, fname="out.gif"):
    images = []
    color_1 = (0, 0, 0)
    color_2 = (255, 255, 255)
    print(bounds)
    im = Image.new("RGB", (bounds[1] - bounds[0], bounds[3] - bounds[2]), color_2)
    last_point = [0, 0]
    gifmod = 4
    total_paths = 0
    for _, path in enumerate(new_paths):
        for _, ele in enumerate(path):
            total_paths += 1
    if total_paths > 100:
        gifmod = int(total_paths / 100)

    i = 0
    for j, path in enumerate(new_paths):
        for _, ele in enumerate(path):
            x1 = np.real(ele.start) - bounds[0]
            y1 = np.imag(ele.start) - bounds[2]
            x2 = np.real(ele.end) - bounds[0]
            y2 = np.imag(ele.end) - bounds[2]
            draw = ImageDraw.Draw(im)
            draw.line((x1, y1, x2, y2), fill=color_1, width=8)
            i += 1
            if i % gifmod == 0 or i >= total_paths - 1:
                im0 = im.copy()
                images.append(im0)
    log.debug(len(images))
    log.debug(f"saving {fname}")
    images[0].save(
        fname,
        save_all=True,
        append_images=images[1:],
        optimize=True,
        duration=int(5000 / float(len(images))),
        loop=1,
    )


@click.command()
@click.option("--file", prompt="image in?", help="svg to process")
@click.option("--folder", default="history", help="folder to output into")
@click.option("--animate/--no-animate", default=False)
@click.option("--overwrite/--no-overwrite", default=True)
@click.option("--skeleton/--no-skeleton", default=False)
@click.option("--autotrace/--no-autotrace", default=False)
@click.option("--minimize/--no-minimize", default=True)
@click.option("--minx", default=0.0, help="minimum x")
@click.option("--maxx", default=190.0, help="maximum x")
@click.option("--miny", default=0.0, help="minimum y")
@click.option("--maxy", default=190.0, help="maximum y")
# @click.option("--minx", default=500, help="minimum x")
# @click.option("--maxx", default=1800, help="maximum x")
# @click.option("--miny", default=-1400, help="minimum y")
# @click.option("--maxy", default=1200, help="maximum y")
@click.option("--junctiondist", default=0, help="junction distance")
@click.option("--seed", default=0, help="random seed")
@click.option("--minpath", default=0, help="min path length")
@click.option("--merge", default=0, help="mege points closer than")
@click.option("--prune", default=0, help="amount of pruning of small things")
@click.option("--simplify", default=0.25, help="simplify level", type=float)
@click.option("--min-segment-length", default=0.2, help="drop segments shorter than this many mm", type=float)
@click.option("--bezier-segments", default=12, help="segments used to sample Bezier curves")
@click.option("--raster-scale", default=10, help="pixels per output unit for tracing", type=float)
@click.option("--png-density", default=600, help="density used when rendering final PNG", type=int)
@click.option("--threshold", default=60, help="percent threshold (0-100)")
def run(
    folder,
    autotrace,
    prune,
    skeleton,
    file,
    simplify,
    overwrite,
    animate,
    minx,
    maxx,
    miny,
    maxy,
    threshold,
    minpath,
    merge,
    minimize,
    junctiondist,
    seed,
    min_segment_length,
    bezier_segments,
    raster_scale,
    png_density,
):
    random.seed(seed)
    imconvert = "convert"
    if os.name == "nt":
        if which("magick"):
            imconvert = "magick"
        elif which("imconvert"):
            imconvert = "imconvert"

    try:
        os.makedirs(folder, exist_ok=True)
    except:
        pass

    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(script_dir)
    if not os.path.isabs(folder):
        folder = os.path.join(script_dir, folder)
    run_timestamp = datetime.now().strftime("%H-%M_on_%Y-%m-%d")
    file_stem = os.path.splitext(ntpath.basename(file))[0]
    safe_stem = "_".join(file_stem.split())
    foldername = os.path.join(folder, f"{safe_stem}_{run_timestamp}")
    gcode_outputs_folder = os.path.join(repo_root, "gcode outputs")
    gcode_output_path = os.path.join(
        gcode_outputs_folder, f"{safe_stem}_{run_timestamp}.gcode"
    )
    try:
        os.makedirs(foldername, exist_ok=True)
    except:
        pass
    try:
        os.makedirs(gcode_outputs_folder, exist_ok=True)
    except:
        pass

    copyfile(file, os.path.join(foldername, ntpath.basename(file)))

    log.info(f"working in {foldername}")
    os.chdir(foldername)
    file = ntpath.basename(file)
    if os.path.exists("image.gc"):
        os.remove("image.gc")

    width = max(1, int(round((maxy - miny) * raster_scale)))
    height = max(1, int(round((maxx - minx) * raster_scale)))
    new_new_paths_flat = []
    bounds = [minx, maxx, miny, maxy]
    if autotrace:
        log.debug("autotrace!")
        run_command(
            [
                imconvert,
                file,
                "-resize",
                f"{width}x{height}",
                "-background",
                "White",
                "-gravity",
                "center",
                "-extent",
                f"{width}x{height}",
                "-threshold",
                f"{threshold}%",
                "-rotate",
                "90",
                "thresholded.png",
            ]
        )
        run_command([imconvert, "thresholded.png", "1.tga"])
        run_command(
            [
                "autotrace",
                "-output-file",
                "potrace.svg",
                "--output-format",
                "svg",
                "--centerline",
                "1.tga",
            ]
        )
        new_new_paths_flat = processAutotraceSVG(
            "potrace.svg",
            "final.svg",
            drawing_area=bounds,
            simplifylevel=simplify,
            minPathLength=minpath,
            mergeSize=merge,
            minimizeMoves=minimize,
            junction_distance=junctiondist,
            bezier_segments=bezier_segments,
            min_segment_length=min_segment_length,
        )
    elif not os.path.exists("potrace.svg") or overwrite:
        if skeleton:
            run_command(
                [
                    imconvert,
                    file,
                    "-resize",
                    f"{width}x{height}",
                    "-background",
                    "White",
                    "-gravity",
                    "center",
                    "-extent",
                    f"{width}x{height}",
                    "-threshold",
                    f"{threshold}%",
                    "thresholded.png",
                ]
            )

            run_command(
                [
                    imconvert,
                    "thresholded.png",
                    "-negate",
                    "-morphology",
                    "Thinning:-1",
                    "Skeleton",
                    "skeleton.png",
                ]
            )

            run_command([imconvert, "skeleton.png", "-negate", "skeleton_negate.png"])

            run_command(
                [imconvert, "skeleton_negate.png", "-rotate", "90", "skeleton_border.png"]
            )

            run_command([imconvert, "skeleton_border.png", "-flip", "skeleton_border_flip.bmp"])

            run_command(
                ["potrace", "-b", "svg", "-o", "potrace.svg", "skeleton_border_flip.bmp"]
            )
        else:
            run_command(
                [
                    imconvert,
                    file,
                    "-resize",
                    f"{width}x{height}",
                    "-background",
                    "White",
                    "-gravity",
                    "center",
                    "-extent",
                    f"{width}x{height}",
                    "-threshold",
                    f"{threshold}%",
                    "thresholded.png",
                ]
            )

            run_command(
                [imconvert, "thresholded.png", "-rotate", "90", "-flip", "thresholded.bmp"]
            )

            run_command(["potrace", "-b", "svg", "-o", "potrace.svg", "-n", "thresholded.bmp"])
            os.remove("thresholded.bmp")

        new_new_paths_flat = processSVG(
            "potrace.svg",
            "final.svg",
            simplifylevel=simplify,
            pruneLittle=prune,
            drawing_area=[minx, maxx, miny, maxy],
            bezier_segments=bezier_segments,
            min_segment_length=min_segment_length,
        )

    final_bounds = get_coords_bounds(lines_to_coords(new_new_paths_flat))
    log.info(
        "final bounds: X {}..{} Y {}..{}",
        fmt_coord(final_bounds[0]),
        fmt_coord(final_bounds[1]),
        fmt_coord(final_bounds[2]),
        fmt_coord(final_bounds[3]),
    )

    run_command(
        [imconvert, "-density", png_density, "final.svg", "-rotate", "270", "final.png"]
    )

    animatefile = ""
    if animate:
        animatefile = "1.gif"
        animateProcess(new_new_paths_flat, bounds, animatefile)
        run_command(
            [imconvert, "-density", png_density, "1.gif", "-rotate", "270", "animation.gif"]
        )
    # os.remove("1.gif")

    copyfile("image.gcode", gcode_output_path)
    log.info("copied gcode output to {}", gcode_output_path)


if __name__ == "__main__":
    run()
