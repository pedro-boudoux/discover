import { useCallback, useEffect, useRef } from "react";
import {
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  type ForceLink,
  type Simulation,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from "d3-force";
import type { NodeDragHandler } from "reactflow";
import type { Node } from "reactflow";
import type { SongNodeData } from "../components/SongNode";

export type SimNode = SimulationNodeDatum & { id: string; isSeed: boolean };
export type SimLink = SimulationLinkDatum<SimNode>;

export function endId(end: SimLink["source"]): string {
  return typeof end === "string" || typeof end === "number"
    ? String(end)
    : (end as SimNode).id;
}

const COLLIDE_RADIUS = 190 / 2 + 28; // NODE_SIZE / 2 + 28
const LINK_DISTANCE = 240;

type SetNodes = (updater: (nds: Node<SongNodeData>[]) => Node<SongNodeData>[]) => void;

export type GraphSimHandle = {
  simNodesRef: React.MutableRefObject<Map<string, SimNode>>;
  simLinksRef: React.MutableRefObject<SimLink[]>;
  simRef: React.MutableRefObject<Simulation<SimNode, SimLink> | null>;
  syncSimulation: (
    nodes: { id: string; isSeed: boolean; x: number; y: number }[],
    edges: { source: string; target: string }[],
    reset: boolean,
  ) => void;
  removeNodesFromSim: (removed: Set<string>) => void;
  handleNodeDragStart: NodeDragHandler;
  handleNodeDrag: NodeDragHandler;
  handleNodeDragStop: NodeDragHandler;
};

export function useGraphSim(setNodes: SetNodes): GraphSimHandle {
  const simRef = useRef<Simulation<SimNode, SimLink> | null>(null);
  const simNodesRef = useRef<Map<string, SimNode>>(new Map());
  const simLinksRef = useRef<SimLink[]>([]);

  useEffect(() => {
    const sim = forceSimulation<SimNode>([])
      .force("collide", forceCollide<SimNode>(COLLIDE_RADIUS).strength(0.95).iterations(2))
      .force(
        "link",
        forceLink<SimNode, SimLink>([]).id((d) => d.id).distance(LINK_DISTANCE).strength(0.18),
      )
      .force("charge", forceManyBody<SimNode>().strength(-160).distanceMax(480))
      .alphaDecay(0.035)
      .velocityDecay(0.4)
      .on("tick", () => {
        const map = simNodesRef.current;
        setNodes((curr) =>
          curr.map((n) => {
            const sn = map.get(n.id);
            if (!sn) return n;
            const x = sn.x ?? n.position.x;
            const y = sn.y ?? n.position.y;
            if (n.position.x === x && n.position.y === y) return n;
            return { ...n, position: { x, y } };
          }),
        );
      });
    simRef.current = sim;
    return () => { sim.stop(); };
  }, [setNodes]);

  const syncSimulation = useCallback(
    (
      structuralNodes: { id: string; isSeed: boolean; x: number; y: number }[],
      structuralEdges: { source: string; target: string }[],
      reset: boolean,
    ) => {
      const sim = simRef.current;
      if (!sim) return;

      if (reset) {
        simNodesRef.current.clear();
        simLinksRef.current = [];
      }

      for (const n of structuralNodes) {
        if (simNodesRef.current.has(n.id)) continue;
        const node: SimNode = { id: n.id, isSeed: n.isSeed, x: n.x, y: n.y };
        if (n.isSeed) { node.fx = n.x; node.fy = n.y; }
        simNodesRef.current.set(n.id, node);
      }

      const linkKey = (l: SimLink) => `${endId(l.source)}->${endId(l.target)}`;
      const existing = new Set(simLinksRef.current.map(linkKey));
      for (const e of structuralEdges) {
        const key = `${e.source}->${e.target}`;
        if (!existing.has(key)) {
          simLinksRef.current.push({ source: e.source, target: e.target });
          existing.add(key);
        }
      }

      sim.nodes(Array.from(simNodesRef.current.values()));
      const linkForce = sim.force<ForceLink<SimNode, SimLink>>("link");
      linkForce?.links(simLinksRef.current);
      sim.alpha(reset ? 1 : 0.85).restart();
    },
    [],
  );

  const removeNodesFromSim = useCallback((removed: Set<string>) => {
    for (const id of removed) simNodesRef.current.delete(id);
    simLinksRef.current = simLinksRef.current.filter(
      (l) => !removed.has(endId(l.source)) && !removed.has(endId(l.target)),
    );
    const sim = simRef.current;
    if (sim) {
      sim.nodes(Array.from(simNodesRef.current.values()));
      const linkForce = sim.force<ForceLink<SimNode, SimLink>>("link");
      linkForce?.links(simLinksRef.current);
      sim.alpha(0.6).restart();
    }
  }, []);

  const handleNodeDragStart: NodeDragHandler = useCallback((_, node) => {
    const sn = simNodesRef.current.get(node.id);
    if (!sn) return;
    sn.fx = node.position.x;
    sn.fy = node.position.y;
    simRef.current?.alphaTarget(0.3).restart();
  }, []);

  const handleNodeDrag: NodeDragHandler = useCallback((_, node) => {
    const sn = simNodesRef.current.get(node.id);
    if (!sn) return;
    sn.fx = node.position.x;
    sn.fy = node.position.y;
  }, []);

  const handleNodeDragStop: NodeDragHandler = useCallback((_, node) => {
    const sn = simNodesRef.current.get(node.id);
    if (!sn) return;
    if (!sn.isSeed) { sn.fx = null; sn.fy = null; }
    simRef.current?.alphaTarget(0);
  }, []);

  return {
    simRef,
    simNodesRef,
    simLinksRef,
    syncSimulation,
    removeNodesFromSim,
    handleNodeDragStart,
    handleNodeDrag,
    handleNodeDragStop,
  };
}
