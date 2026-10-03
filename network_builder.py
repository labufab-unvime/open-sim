#!/usr/bin/env python3
"""
Módulo NetworkBuilder (v6.1)
- [FIX v6.1] REESCRITA LA FÍSICA (LA DEFINITIVA, AHORA SÍ).
- La v6.0 estaba rota: no asignaba W_max (lado largo) y H_min (lado corto)
  correctamente en la fórmula, dando resistencias (R=5.59e12) 8 veces
  mayores a las del benchmark (R=6.73e11).
- Esta versión (v6.1) SÍ asigna W_max y H_min correctamente ANTES de
  aplicar la fórmula de Bruus (R = 12*mu*L / (W_max * H_min^3 * F(a))),
  lo cual es críticamente necesario para que la física sea válida.
"""

import numpy as np
import logging
import math

class NetworkBuilder:
    def __init__(self):
        # Tolerancia aumentada para asegurar la conexión
        self.NODE_SNAP_TOL_um = 600.0
        self.NODE_SNAP_TOL = self.NODE_SNAP_TOL_um * 1e-6

    def calculate_resistance(self, L_um, w_um, h_um, mu_Pas):
        """
        [FIX v6.1] Calcula la resistencia hidráulica usando la
        solución analítica completa (Poiseuille para canal rectangular).
        Válida para CUALQUIER aspect ratio.

        Basado en Bruus (2008), Eq. 2.45
        R_h = 12 * mu * L / ( W_max * H_min^3 * F(a) )
        donde 'a' = H_min / W_max <= 1
        """

        L_m = L_um * 1e-6
        w_m = w_um * 1e-6 # Ancho del SVG (ej. 150 µm)
        h_m = h_um * 1e-6 # Altura global (ej. 100 µm)

        if w_m <= 1e-12 or h_m <= 1e-12 or L_m <= 0:
            return 1e20 # Resistencia infinita

        # [FIX v6.1] Asignación crítica de W_max y H_min
        # La fórmula de Bruus REQUIERE que H sea el lado corto y W el largo.
        H_min = min(w_m, h_m)
        W_max = max(w_m, h_m)

        # Calcular el aspect ratio (a = corto / largo)
        a = H_min / W_max

        # Calcular el factor de corrección F(a)
        # (solución de serie de Fourier)
        # F(a) = 1 - (192 * a) / (pi^5) * sum[ tanh(n*pi / (2*a)) / n^5 ]

        F_sum = 0.0
        # La serie converge rápido, n=1, 3, 5, 7, 9 es suficiente
        for n in range(1, 10, 2): # n = 1, 3, 5, 7, 9
            try:
                # [FIX v6.1] Corregido el término de la sumatoria (era W/H)
                tanh_term = math.tanh(n * math.pi / (2.0 * a))
                F_sum += tanh_term / (n**5)
            except OverflowError:
                # Si tanh(inf), el término es 1.0
                F_sum += 1.0 / (n**5)

        F_correction = 1.0 - ( (192.0 * a) / (math.pi**5) ) * F_sum

        if F_correction <= 0.01:
            # Si a=1 (cuadrado), F=0.85. Si a=0.1, F=0.99. Si a->0, F=1.
            # Nunca debería ser 0.01.
            logging.warning(f"F_correction factor {F_correction} is very low. a={a}")
            # Usar la aproximación simple de Hele-Shaw (para a << 1)
            F_correction = 1.0 - 0.63 * a

        # Calcular Resistencia Hidráulica (Pa·s / m³)
        try:
            R = (12.0 * mu_Pas * L_m) / ( W_max * (H_min**3) * F_correction )
        except (ZeroDivisionError, OverflowError):
             return 1e20

        if not np.isfinite(R):
            return 1e20

        return R

    def build_network(self, parsed_data, height_m, mu,
                        selected_inlets=None, selected_outlets=None,
                        selected_channels=None, selected_cameras=None):
        """Construye la red de nodos y edges - Lógica v4.0"""

        channels = selected_channels if selected_channels else parsed_data['channels']
        cameras = selected_cameras if selected_cameras else parsed_data['cameras']
        inlets = selected_inlets if selected_inlets else parsed_data['inlets']
        outlets = selected_outlets if selected_outlets else parsed_data['outlets']

        nodes = []
        node_types = []
        edges = []
        point_to_node_idx = {} # Mapeo de (x_um, y_um) -> node_idx

        logging.info(f"Building network with: {len(channels)} channels, {len(cameras)} chambers, {len(inlets)} inlets, {len(outlets)} outlets")

        def _get_node_idx(point_um, n_type='junction'):
            """Helper robusto para encontrar o crear nodos."""
            # 1. Buscar por proximidad a CUALQUIER nodo existente
            for i, existing_node in enumerate(nodes):
                existing_node_um = (existing_node[0] * 1e6, existing_node[1] * 1e6)
                dist = math.hypot(point_um[0] - existing_node_um[0], point_um[1] - existing_node_um[1])
                if dist <= self.NODE_SNAP_TOL_um:
                    logging.info(f"Snapped point ({point_um[0]:.0f}, {point_um[1]:.0f}) to existing node {i} ({node_types[i]}) (dist: {dist:.1f}µm)")
                    return i

            # 2. Si no se encuentra, crear un nuevo nodo
            nodes.append((point_um[0] * 1e-6, point_um[1] * 1e-6))
            node_types.append(n_type)
            new_node_idx = len(nodes) - 1
            logging.info(f"Created new node {new_node_idx} ({n_type}) at ({point_um[0]:.0f}, {point_um[1]:.0f})µm")
            return new_node_idx

        # --- 1. Crear Nodos de Inlets y Outlets PRIMERO ---
        inlet_nodes_idx = []
        for i, inlet in enumerate(inlets):
            node_idx = _get_node_idx(inlet['center'], 'inlet')
            inlet_nodes_idx.append(node_idx)
            logging.info(f"Inlet {i} '{inlet['id']}' mapped to node {node_idx}")

        outlet_nodes_idx = []
        for i, outlet in enumerate(outlets):
            node_idx = _get_node_idx(outlet['center'], 'outlet')
            outlet_nodes_idx.append(node_idx)
            logging.info(f"Outlet {i} '{outlet['id']}' mapped to node {node_idx}")

        # --- 2. Crear Nodos y Edges para Cámaras ---
        for cam in cameras:
            if cam['type'] != 'rectangle':
                logging.warning(f"Warning: Skipping non-rectangular camera {cam['id']}")
                continue

            x, y, w, h = cam['bounds']
            logging.info(f"Info: Assuming VERTICAL flow for camera {cam['id']}")

            top_c_um = (x + w/2, y)
            bot_c_um = (x + w/2, y + h)

            top_node_idx = _get_node_idx(top_c_um, 'camera_connection')
            bot_node_idx = _get_node_idx(bot_c_um, 'camera_connection')

            length_um, width_um = h, w

            # [FIX v6.1] Llamada a la nueva función de resistencia
            # (height_m * 1e6) convierte la altura de m a µm
            R_cam = self.calculate_resistance(length_um, width_um, height_m * 1e6, mu)

            edges.append({
                'id': cam['id'], 'n1': top_node_idx, 'n2': bot_node_idx,
                'length_um': length_um, 'width_um': width_um, 'R': R_cam,
                'type': 'channel', # Tratado como canal para el solver
                'points_m': np.array([(top_c_um[0]*1e-6, top_c_um[1]*1e-6),
                                     (bot_c_um[0]*1e-6, bot_c_um[1]*1e-6)])
            })
            logging.info(f"Created Chamber-Edge {cam['id']}: nodes {top_node_idx}->{bot_node_idx}, R={R_cam:.2e}")

        # --- 3. Crear Edges para Canales ---
        for ch in channels:
            start_point_um = ch['start_point']
            end_point_um = ch['end_point']

            start_node = _get_node_idx(start_point_um, 'junction')
            end_node = _get_node_idx(end_point_um, 'junction')

            length_um = math.hypot(end_point_um[0]-start_point_um[0], end_point_um[1]-start_point_um[1])
            width_um = ch.get('stroke_width', 150.0)

            # [FIX v6.1] Llamada a la nueva función de resistencia
            R_chan = self.calculate_resistance(length_um, width_um, height_m * 1e6, mu)

            edges.append({
                'id': ch.get('id'), 'n1': start_node, 'n2': end_node,
                'length_um': length_um, 'width_um': width_um, 'R': R_chan,
                'type': 'channel',
                'points_m': np.array([(start_point_um[0]*1e-6, start_point_um[1]*1e-6),
                                     (end_point_um[0]*1e-6, end_point_um[1]*1e-6)])
            })
            logging.info(f"Created Channel-Edge {ch['id']}: nodes {start_node}->{end_node}, R={R_chan:.2e}")

        # --- 4. Información de la Red ---
        print(f"\nNetwork built: {len(nodes)} nodes, {len(edges)} edges")
        print("\n=== NODE INFORMATION ===")
        for i, (node, ntype) in enumerate(zip(nodes, node_types)):
            print(f"Node {i} ({ntype}): ({node[0]*1e6:.0f}, {node[1]*1e6:.0f}) µm")

        return nodes, node_types, edges, inlet_nodes_idx, outlet_nodes_idx, cameras
