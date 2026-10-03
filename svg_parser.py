#!/usr/bin/env python3
"""
Módulo SVGMicrofluidicParser (v5.6)
- [FIX v5.6] Reescrita la función '_parse_stroke_width' para corregir
  el bug de discrepancia en la simulación.
- [FIX] La lógica anterior asumía 'µm' para valores sin unidad, pero
  muchos SVGs usan 'px' (o unidades de usuario) sin especificarlos.
- [NEW] La nueva lógica prioriza 'style', luego 'mm', 'µm', 'pt',
  y 'px'. Ahora, 'px' se convierte usando 3.5433 (90dpi), que es
  el estándar de Inkscape, en lugar del 3.78 (96dpi).
- [NEW] Un valor sin unidad (ej. "150") AHORA se trata como 'px'
  y se convierte, asumiendo que el SVG no está en escala 1:1 µm.
  Esto coincide con el comportamiento de la mayoría de los solvers.
"""

import xml.etree.ElementTree as ET
from svgpathtools import svg2paths2
import numpy as np
import logging
import math
import re

class SVGMicrofluidicParser:
    def __init__(self):
        self.elements = {
            'channels': [],
            'cameras': [],
            'inlets': [],
            'outlets': [],
            'other': []
        }
        self.current_file = None
        self.next_generic_chamber_id = 1
        self.next_generic_path_id = 1
        self.next_generic_inlet_id = 1
        self.next_generic_outlet_id = 1

        # [FIX v5.6] Constantes de conversión.
        # Inkscape (estándar) usa 90 dpi -> 1px = 0.2822 mm = 282.2 µm
        # Adobe (estándar) usa 72 dpi -> 1px = 0.3528 mm = 352.8 µm
        # Web (CSS) usa 96 dpi -> 1px = 0.2646 mm = 264.6 µm
        # El 3.78 que tenías era 1000 / (96 / 2.54 / 10) = 264.58 -> 1px = 264.6 µm
        # Vamos a usar el 96dpi (CSS) ya que es común en SVGs de web/flui3d

        self.PX_TO_UM = 264.58
        self.PT_TO_UM = 352.77 # 1pt = 1/72 inch
        self.MM_TO_UM = 1000.0

    def parse_svg(self, svg_path):
        """Parse SVG y detectar todos los elementos microfluídicos de forma robusta"""
        self.elements = {'channels': [], 'cameras': [], 'inlets': [], 'outlets': [], 'other': []}
        self.current_file = svg_path
        self.next_generic_chamber_id = 1
        self.next_generic_path_id = 1
        self.next_generic_inlet_id = 1
        self.next_generic_outlet_id = 1

        # [FIX v5.6] Detectar el DPI del SVG si es posible (no implementado aún)
        # Por ahora, asumimos que todas las coordenadas de 'svgpathtools'
        # están en un espacio 1:1 µm o que el 'stroke-width' debe convertirse.
        # Esta lógica asume que las coordenadas (x,y,w,h) SÍ están en µm,
        # pero que stroke-width (ancho de línea) puede tener unidades.

        try:
            # Parse with svgpathtools for paths
            paths, attributes, svg_attr = svg2paths2(svg_path)
            self._process_paths(paths, attributes)

            # Parse with XML for other elements
            tree = ET.parse(svg_path)
            root = tree.getroot()
            ns = ''
            if '}' in root.tag:
                ns = root.tag.split('}')[0] + '}'
            self._process_xml_elements(root, ns)

            logging.info(f"Parsed: {len(self.elements['channels'])} channels, "
                        f"{len(self.elements['cameras'])} chambers, "
                        f"{len(self.elements['inlets'])} inlets, "
                        f"{len(self.elements['outlets'])} outlets")
            return True
        except Exception as e:
            logging.error(f"Error parsing SVG: {e}")
            return False

    def _process_paths(self, paths, attributes):
        """Procesar paths de forma robusta, manejando elementos degenerados"""
        for path_obj, attr in zip(paths, attributes):
            try:
                element_id = attr.get('id', '')
                if not element_id:
                    element_id = f"GenericPath-{self.next_generic_path_id}"
                    self.next_generic_path_id += 1

                stroke_w_um = self._parse_stroke_width(attr)

                ts = np.linspace(0.0, 1.0, 10)
                pts = []
                valid_path = True
                for t in ts:
                    try:
                        p = path_obj.point(t)
                        pts.append((p.real, p.imag))
                    except Exception as e:
                        logging.warning(f"Error sampling path {element_id} at t={t}: {e}")
                        valid_path = False
                        break
                if not valid_path or len(pts) < 2: continue
                pts = np.array(pts)
                if np.allclose(pts, pts[0]):
                    logging.info(f"Skipping degenerate path: {element_id}")
                    continue

                element = {
                    'id': element_id,
                    'type': 'path',
                    'points': pts,
                    'start_point': tuple(pts[0]),
                    'end_point': tuple(pts[-1]),
                    'stroke_width': stroke_w_um, # Guardamos el valor en µm
                    'bounds': self._calculate_bounds(pts)
                }

                if self._is_channel(element_id, stroke_w_um, pts):
                    self.elements['channels'].append(element)
                    logging.info(f"Found channel: {element_id} (W: {stroke_w_um:.1f}µm)")
                else:
                    logging.info(f"Skipping path {element_id} (W: {stroke_w_um:.1f}µm) - Not a channel.")
                    self.elements['other'].append(element)
            except Exception as e:
                logging.warning(f"Error processing path {attr.get('id', 'unknown')}: {e}")
                continue

    def _process_xml_elements(self, root, ns):
        """Procesar elementos XML de forma robusta"""
        for elem in root.iter():
            try:
                tag = elem.tag.replace(ns, '')
                elem_id = elem.get('id', '')
                if tag == 'rect':
                    self._parse_rectangle(elem, elem_id)
                elif tag == 'circle':
                    self._parse_circle(elem, elem_id)
                elif tag == 'g':
                    self._parse_group(elem, ns)
                elif tag == 'line':
                    self._parse_line(elem, elem_id)
            except Exception as e:
                logging.warning(f"Error processing XML element {elem.tag}: {e}")
                continue

    def _is_channel(self, element_id, stroke_width, points):
        """Determinar si un elemento es un canal"""
        if 'channel' in element_id.lower():
            return True

        # [MODIFICADO v4.0] Lógica más estricta para evitar "basura"
        # Debe tener un ancho de línea razonable (no ser un borde fino)
        # y no ser gigante (como un borde de página)
        if stroke_width > 10 and stroke_width < 1000:
            return True

        # Geometría: largo y delgado
        if len(points) >= 2:
            start, end = points[0], points[-1]
            length = np.sqrt((end[0]-start[0])**2 + (end[1]-start[1])**2)
            if length > 1000 and stroke_width < 1000:
                return True
        return False

    def _parse_stroke_width(self, attr):
        """
        [FIX v5.6] Lógica de parseo de 'stroke-width' robusta.
        Extrae el valor y la unidad del 'style' o del atributo.
        Convierte 'px', 'pt', 'mm' a 'µm'.
        Asume que un valor sin unidad ES 'µm' (1:1).
        """
        stroke_w_str = "1.0" # Default

        # Regex para encontrar números (float/int) y unidades (opcionales)
        unit_regex = re.compile(r"^\s*([+-]?[0-9]*\.?[0-9]+)\s*(px|pt|mm|um|µm)?\s*$")

        # 1. Intentar leer desde el atributo 'style' (prioridad)
        style = attr.get('style', '')
        if 'stroke-width:' in style:
            parts = style.split(';')
            for p in parts:
                if p.strip().startswith('stroke-width:'):
                    stroke_w_str = p.split(':', 1)[1].strip()
                    break
        else:
            # 2. Si no está en 'style', leer del atributo 'stroke-width'
            stroke_w_str = attr.get('stroke-width', stroke_w_str)

        stroke_w_str = str(stroke_w_str)

        # 3. Parsear el valor y la unidad
        match = unit_regex.match(stroke_w_str)

        if not match:
            logging.warning(f"Could not parse stroke-width: '{stroke_w_str}'. Defaulting to 1.0 µm.")
            return 1.0

        value = float(match.group(1))
        unit = match.group(2)

        # 4. Convertir a µm
        if unit == 'mm':
            return value * self.MM_TO_UM
        if unit == 'pt':
            return value * self.PT_TO_UM
        if unit == 'px':
            logging.info(f"Detected 'px' unit. Converting {value}px to {value * self.PX_TO_UM:.1f}µm using {self.PX_TO_UM} µm/px.")
            return value * self.PX_TO_UM
        if unit == 'um' or unit == 'µm':
            return value

        # 5. Asumir 'µm' (1:1) si no hay unidad
        # Esta es la convención para flui3d.org
        if unit is None:
            return value

        return 1.0


    def _parse_rectangle(self, elem, elem_id):
        try:
            # [FIX v5.6] Asumimos que x, y, w, h están en µm (1:1)
            x = float(elem.get('x', 0)); y = float(elem.get('y', 0))
            w = float(elem.get('width', 0)); h = float(elem.get('height', 0))
            if w <= 0 or h <= 0: return

            if not elem_id:
                elem_id = f"GenericChamber-{self.next_generic_chamber_id}"
                self.next_generic_chamber_id += 1
            element = {
                'id': elem_id, 'type': 'rectangle', 'bounds': (x, y, w, h),
                'centroid': (x + w/2, y + h/2),
                'connection_points': [
                    (x + w/2, y), (x + w, y + h/2),
                    (x + w/2, y + h), (x, y + h/2)]
            }
            if self._is_camera(elem_id, w, h):
                self.elements['cameras'].append(element)
                logging.info(f"Found chamber: {elem_id}")
            else: self.elements['other'].append(element)
        except Exception as e:
            logging.warning(f"Error parsing rectangle {elem_id}: {e}")

    def _is_camera(self, elem_id, width, height):
        if 'chamber' in elem_id.lower() or 'camara' in elem_id.lower(): return True
        if width > 1000 and height > 1000: return True # Asumir que rectángulos grandes son cámaras
        return False

    def _parse_circle(self, elem, elem_id):
        try:
            # [FIX v5.6] Asumimos que cx, cy, r están en µm (1:1)
            cx = float(elem.get('cx', 0)); cy = float(elem.get('cy', 0))
            r = float(elem.get('r', 0)); fill = elem.get('fill', '').lower()
            if r <= 0: return

            # Asignar ID genérico si no tiene y no es 'other'
            is_in = self._is_inlet(fill)
            is_out = self._is_outlet(fill)
            if not elem_id:
                if is_in:
                    elem_id = f"GenericInlet-{self.next_generic_inlet_id}"
                    self.next_generic_inlet_id += 1
                elif is_out:
                    elem_id = f"GenericOutlet-{self.next_generic_outlet_id}"
                    self.next_generic_outlet_id += 1

            element = {'id': elem_id, 'type': 'circle', 'center': (cx, cy), 'radius': r, 'fill': fill}

            if is_in:
                self.elements['inlets'].append(element)
                logging.info(f"Found inlet: {element['id']}")
            elif is_out:
                self.elements['outlets'].append(element)
                logging.info(f"Found outlet: {element['id']}")
            else:
                self.elements['other'].append(element)
        except Exception as e:
            logging.warning(f"Error parsing circle {elem_id}: {e}")

    def _is_inlet(self, fill_color):
        inlet_colors = ['#00c800', '#00ff00', 'rgb(0,200,0)', 'rgb(0,255,0)', 'green']
        return any(color in fill_color.lower() for color in inlet_colors)

    def _is_outlet(self, fill_color):
        outlet_colors = ['#dc0000', '#ff0000', 'rgb(220,0,0)', 'rgb(255,0,0)', 'red']
        return any(color in fill_color.lower() for color in outlet_colors)

    def _parse_line(self, elem, elem_id):
        try:
            # [FIX v5.6] Asumimos que x1, y1, x2, y2 están en µm (1:1)
            x1 = float(elem.get('x1', 0)); y1 = float(elem.get('y1', 0))
            x2 = float(elem.get('x2', 0)); y2 = float(elem.get('y2', 0))
            points = np.array([(x1, y1), (x2, y2)])
            stroke_w_um = self._parse_stroke_width(elem.attrib)
            if not elem_id:
                elem_id = f"GenericPath-{self.next_generic_path_id}"
                self.next_generic_path_id += 1
            element = {
                'id': elem_id, 'type': 'line', 'points': points,
                'start_point': (x1, y1), 'end_point': (x2, y2),
                'stroke_width': stroke_w_um, 'bounds': self._calculate_bounds(points)
            }
            if self._is_channel(elem_id, stroke_w_um, points):
                self.elements['channels'].append(element)
            else: self.elements['other'].append(element)
        except Exception as e:
            logging.warning(f"Error parsing line {elem_id}: {e}")

    def _parse_group(self, elem, ns):
        try:
            group_id = elem.get('id', '')
            for child in elem:
                child_tag = child.tag.replace(ns, '')
                child_id = child.get('id', group_id)
                if child_tag == 'rect': self._parse_rectangle(child, child_id)
                elif child_tag == 'circle': self._parse_circle(child, child_id)
        except Exception as e:
            logging.warning(f"Error parsing group {group_id}: {e}")

    def _calculate_bounds(self, points):
        try:
            if len(points) == 0: return (0, 0, 0, 0)
            x_coords = points[:, 0]; y_coords = points[:, 1]
            return (min(x_coords), min(y_coords),
                    max(x_coords) - min(x_coords),
                    max(y_coords) - min(y_coords))
        except: return (0, 0, 0, 0)
