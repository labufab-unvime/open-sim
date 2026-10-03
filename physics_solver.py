#!/usr/bin/env python3
"""
Módulo PhysicsSolver (v5.0)
- [FIX v5.0] Lógica de Boundary Conditions (BC) reescrita.
  El solver (v4.1) estaba roto: trataba un Inlet de Caudal (Flow)
  como un nodo de Presión Fija (Dirichlet), violando la conservación de masa.
- [FIX] Ahora, un Inlet de Caudal se trata como un nodo de Flujo Fijo
  (Neumann), permitiendo que el solver calcule su presión (P_inlet)
  correctamente usando Análisis Nodal.
- [FIX] La regularización (1e-12) era un 'red herring', se cambió a 1e-25
  para evitar cualquier influencia, aunque el bug real era la lógica de BC.
"""

import numpy as np
import logging

def solve_network_poiseuille(nodes, node_types, edges, inlet_nodes, outlet_nodes, inlet_conditions):
    """Resuelve la red hidráulica lineal (Hagen-Poiseuille) usando Análisis Nodal"""
    N = len(nodes)

    if not inlet_nodes:
        logging.error("Error: No inlets defined. Simulation aborted.")
        return np.zeros(N), edges
    if not outlet_nodes:
        logging.error("Error: No outlets defined. Simulation aborted.")
        return np.zeros(N), edges

    # --- INICIO DE LA LÓGICA CORREGIDA (v5.0) ---

    fixed_pressure = {}     # Nodos tipo Dirichlet (Presión Fija)
    flow_injections = {}    # Nodos tipo Neumann (Caudal Fijo)

    # 1. Aplicar condiciones de Outlets (Presión Fija 0 Pa por defecto)
    for outlet_node in outlet_nodes:
        if outlet_node not in fixed_pressure:
            fixed_pressure[outlet_node] = 0.0
            logging.info(f"Outlet node {outlet_node} set to 0 Pa (Dirichlet BC)")

    # 2. Interpretar las condiciones de Inlet
    for bc in inlet_conditions:
        node = bc['node']
        if bc['type'] == 'pressure':
            # MODO PRESIÓN: El inlet es un nodo de Presión Fija
            fixed_pressure[node] = bc['value']
            logging.info(f"Inlet node {node} set to P={bc['value']} Pa (Dirichlet BC)")

        elif bc['type'] == 'flow':
            # MODO CAUDAL: El inlet es un nodo de Caudal Fijo
            # Su presión es DESCONOCIDA.
            flow_injections[node] = bc['value']
            logging.info(f"Inlet node {node} set to Q={bc['value']:.2e} m³/s (Neumann BC)")

            # Si el inlet estaba en fixed_pressure (por ser outlet?), lo quitamos.
            if node in fixed_pressure:
                logging.warning(f"Node {node} was fixed pressure, removing for flow BC.")
                del fixed_pressure[node]

    # 3. Determinar qué nodos tienen presión desconocida
    unknown_nodes = [i for i in range(N) if i not in fixed_pressure]

    # --- FIN DE LA LÓGICA CORREGIDA (v5.0) ---

    if len(unknown_nodes) == 0:
        logging.info("All nodes have fixed pressure")
        pressures = np.zeros(N)
        for node, pressure in fixed_pressure.items():
            pressures[node] = pressure
    else:
        logging.info(f"Solving for {len(unknown_nodes)} unknown nodes")

        # Build matrix system (Ax = b)
        idx_map = {node: i for i, node in enumerate(unknown_nodes)}
        M = len(unknown_nodes)
        A = np.zeros((M, M))  # Matriz de Conductancia
        b = np.zeros(M)       # Vector de Fuentes

        # Llenar la matriz A (Conductancias) y el vector b (Presiones Fijas)
        for edge in edges:
            n1, n2, R = edge['n1'], edge['n2'], edge['R']
            if R <= 0 or R == float('inf') or R > 1e20: continue

            G = 1.0 / R # Conductancia

            if n1 in idx_map: # n1 es desconocido
                i = idx_map[n1]
                A[i, i] += G
                if n2 in idx_map: # n2 también es desconocido
                    j = idx_map[n2]; A[i, j] -= G
                else: # n2 es conocido (presión fija)
                    b[i] += G * fixed_pressure.get(n2, 0.0)

            if n2 in idx_map: # n2 es desconocido
                i = idx_map[n2]
                A[i, i] += G
                if n1 in idx_map: # n1 también es desconocido
                    j = idx_map[n1]; A[i, j] -= G
                else: # n1 es conocido (presión fija)
                    b[i] += G * fixed_pressure.get(n1, 0.0)

        # Llenar el vector b (Fuentes de Caudal)
        # (Según LCK: Sum(G_ij * (P_j - P_i)) = Q_in, i)
        # (Reordenado: Sum(G_ij * P_j) = Q_in, i + Sum(G_ij * P_i_fijo))
        # (El 'b' actual es b = Sum(G_ij * P_i_fijo))
        # (Por lo tanto, la inyección se suma: b_final = b + Q_in)

        for node, Q_in in flow_injections.items():
            if node in idx_map:
                i = idx_map[node]
                b[i] += Q_in # Caudal que ENTRA es POSITIVO
            else:
                logging.warning(f"Flow injection {Q_in} at {node} ignored (node has fixed pressure).")


        # Solve system
        try:
            # [FIX v5.0] Regularización muy pequeña para no afectar los cálculos
            A += np.eye(M) * 1e-25
            p_unknown = np.linalg.solve(A, b)
            logging.info("System solved successfully")
        except np.linalg.LinAlgError:
            logging.warning("Singular matrix - using least squares")
            p_unknown = np.linalg.lstsq(A, b, rcond=1e-10)[0]

        if not np.all(np.isfinite(p_unknown)):
            logging.error("Error: Solution contains NaN or Inf. Network is likely disconnected.")
            p_unknown = np.zeros_like(p_unknown)

        pressures = np.zeros(N)
        for node, pressure in zip(unknown_nodes, p_unknown):
            pressures[node] = pressure
        for node, pressure in fixed_pressure.items():
            pressures[node] = pressure

    # Calculate flows
    total_flow = 0
    for edge in edges:
        p1 = pressures[edge['n1']]; p2 = pressures[edge['n2']]
        edge['Q_m3s'] = (p1 - p2) / edge['R'] if edge['R'] > 0 else 0.0
        edge['Q_uLmin'] = edge['Q_m3s'] * 1e9 * 60.0
        edge['deltaP'] = p1 - p2
        edge['avg_pressure'] = 0.5 * (p1 + p2)
        if edge['type'] == 'channel':
            total_flow += abs(edge['Q_uLmin'])
            logging.info(f"ID: {edge['id']}: Q = {edge['Q_uLmin']:.6f} µL/min, ΔP = {edge['deltaP']:.6f} Pa")

    logging.info(f"Total flow (sum of abs values): {total_flow:.6f} µL/min")
    return pressures, edges
