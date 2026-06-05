import { useCallback, useEffect, useRef, useState } from "react";
import {
  addEdge,
  useEdgesState,
  useNodesState,
  type Edge,
  type Node,
  type NodeDragHandler,
  type NodeMouseHandler,
} from "reactflow";
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
import { Graph } from "./components/Graph";
import { GraphInfo } from "./components/GraphInfo";
import { NodePopover } from "./components/NodePopover";
import { SearchBar } from "./components/SearchBar";
import { NODE_SIZE, type SongNodeData } from "./components/SongNode";
import { expandFromTrack, getSongStatus, seedSong } from "./api";
import { LoadingText, Spinner } from "./components/Loader";
import type { ExpansionParams, SongSearchResult } from "./types";

type SeedingPhase = null | "checking" | "warm" | "cold";

const COLLIDE_RADIUS = NODE_SIZE / 2 + 28;
const LINK_DISTANCE = 240;
const ARC_RADIUS = 260;

type Vec = { x: number; y: number };

type SimNode = SimulationNodeDatum & { id: string; isSeed: boolean };
type SimLink = SimulationLinkDatum<SimNode>;

function endId(end: SimLink["source"]): string {
  return typeof end === "string" || typeof end === "number"
    ? String(end)
    : (end as SimNode).id;
}

function arcAround(count: number, parentPos: Vec): Vec[] {
  const arcStart = -Math.PI * 0.85;
  const arcEnd = Math.PI * 0.85;
  const positions: Vec[] = [];
  for (let i = 0; i < count; i++) {
    const t = count === 1 ? 0.5 : i / (count - 1);
    const angle = arcStart + (arcEnd - arcStart) * t;
    positions.push({
      x: parentPos.x + ARC_RADIUS * Math.sin(angle),
      y: parentPos.y + ARC_RADIUS * (0.4 + 0.6 * Math.cos(angle)),
    });
  }
  return positions;
}

type PopoverState = {
  nodeId: string;
  label: string;
  isSeed: boolean;
  x: number;
  y: number;
};

export default function App() {
  const [nodes, setNodes, onNodesChange] = useNodesState<SongNodeData>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [popover, setPopover] = useState<PopoverState | null>(null);
  const [loading, setLoading] = useState(false);
  const [seedingPhase, setSeedingPhase] = useState<SeedingPhase>(null);
  const [error, setError] = useState<string | null>(null);

  const simRef = useRef<Simulation<SimNode, SimLink> | null>(null);
  const simNodesRef = useRef<Map<string, SimNode>>(new Map());
  const simLinksRef = useRef<SimLink[]>([]);

  useEffect(() => {
    const sim = forceSimulation<SimNode>([])
      .force(
        "collide",
        forceCollide<SimNode>(COLLIDE_RADIUS).strength(0.95).iterations(2),
      )
      .force(
        "link",
        forceLink<SimNode, SimLink>([])
          .id((d) => d.id)
          .distance(LINK_DISTANCE)
          .strength(0.18),
      )
      .force(
        "charge",
        forceManyBody<SimNode>().strength(-160).distanceMax(480),
      )
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
        if (n.isSeed) {
          node.fx = n.x;
          node.fy = n.y;
        }
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

  const handleSeed = useCallback(
    async (song: SongSearchResult) => {
      setSeedingPhase("checking");
      setError(null);
      try {
        let cached = false;
        try {
          const status = await getSongStatus(song.track_id);
          cached = status.cached;
        } catch {
          // status check failures shouldn't block the seed flow
        }
        setSeedingPhase(cached ? "warm" : "cold");

        const isFirstSeed = simNodesRef.current.size === 0;

        await seedSong(song.track_id);
        const initialChildren = await expandFromTrack(
          song.track_id,
          "recommendations",
          { k: 8, lambda: 0.7, niche: false, maxDepth: 3, excludeIds: [] },
        );

        let seedPos: Vec;
        if (isFirstSeed) {
          seedPos = { x: 0, y: 0 };
        } else {
          const existingSim = simNodesRef.current.get(song.track_id);
          if (existingSim) {
            seedPos = { x: existingSim.x ?? 0, y: existingSim.y ?? 0 };
          } else {
            const maxX = Math.max(
              ...Array.from(simNodesRef.current.values()).map((n) => n.x ?? 0),
              0,
            );
            seedPos = { x: maxX + 600, y: 0 };
          }
        }

        const childPositions = arcAround(initialChildren.length, seedPos);
        const childPosMap = new Map(
          initialChildren.map((c, i) => [c.track_id, childPositions[i]]),
        );

        const seedNode: Node<SongNodeData> = {
          id: song.track_id,
          type: "song",
          position: seedPos,
          data: { name: song.name, artist: song.artist, image: song.image, isSeed: true },
        };

        const newChildNodes: Node<SongNodeData>[] = initialChildren
          .filter((c) => !simNodesRef.current.has(c.track_id))
          .map((c) => ({
            id: c.track_id,
            type: "song",
            position: childPosMap.get(c.track_id)!,
            data: {
              name: c.name,
              artist: c.artist,
              image: c.image,
              isSeed: false,
              similarity: c.similarity,
              listeners: c.listeners,
            },
          }));

        const newEdges: Edge[] = initialChildren.map((c) => ({
          id: `${song.track_id}->${c.track_id}`,
          source: song.track_id,
          target: c.track_id,
        }));

        if (isFirstSeed) {
          setNodes([seedNode, ...newChildNodes]);
          setEdges(newEdges);
        } else {
          setNodes((nds) => {
            const base = nds.some((n) => n.id === song.track_id)
              ? nds.map((n) =>
                  n.id === song.track_id
                    ? { ...n, data: { ...n.data, isSeed: true } }
                    : n,
                )
              : [...nds, seedNode];
            return [...base, ...newChildNodes];
          });
          setEdges((eds) => {
            let next = eds;
            for (const e of newEdges) {
              if (!next.some((existing) => existing.id === e.id)) {
                next = addEdge(e, next);
              }
            }
            return next;
          });
        }

        syncSimulation(
          [
            { id: song.track_id, isSeed: true, x: seedPos.x, y: seedPos.y },
            ...newChildNodes.map((n) => ({
              id: n.id,
              isSeed: false,
              x: n.position.x,
              y: n.position.y,
            })),
          ],
          newEdges.map((e) => ({ source: e.source!, target: e.target! })),
          isFirstSeed,
        );
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to seed song");
      } finally {
        setSeedingPhase(null);
      }
    },
    [setNodes, setEdges, syncSimulation],
  );

  const handleNodeClick: NodeMouseHandler = useCallback((event, node) => {
    const data = node.data as SongNodeData;
    setPopover({
      nodeId: node.id,
      label: `${data.name} — ${data.artist}`,
      isSeed: data.isSeed,
      x: event.clientX,
      y: event.clientY,
    });
  }, []);

  const handleExpand = useCallback(
    async (params: ExpansionParams) => {
      if (!popover) return;
      setLoading(true);
      setError(null);
      try {
        const parentId = popover.nodeId;
        const knownIds = Array.from(simNodesRef.current.keys());
        const excludeIds = params.allowDuplicates
          ? []
          : knownIds.filter((id) => id !== parentId);
        const children = await expandFromTrack(parentId, params.method, {
          k: params.k,
          lambda: params.lambda,
          niche: params.niche,
          maxDepth: params.maxDepth,
          excludeIds,
        });

        const parentSim = simNodesRef.current.get(parentId);
        const parentPos: Vec = { x: parentSim?.x ?? 0, y: parentSim?.y ?? 0 };

        const newChildren = children.filter(
          (c) => !simNodesRef.current.has(c.track_id),
        );
        const initialPositions = arcAround(newChildren.length, parentPos);

        const newNodes: Node<SongNodeData>[] = newChildren.map((c, i) => ({
          id: c.track_id,
          type: "song",
          position: initialPositions[i],
          data: {
            name: c.name,
            artist: c.artist,
            image: c.image,
            isSeed: false,
            similarity: c.similarity,
            listeners: c.listeners,
          },
        }));

        const newEdges: Edge[] = children.map((c) => ({
          id: `${parentId}->${c.track_id}`,
          source: parentId,
          target: c.track_id,
        }));

        setNodes((nds) => [...nds, ...newNodes]);
        setEdges((eds) => {
          let next = eds;
          for (const e of newEdges) {
            if (!next.some((existing) => existing.id === e.id)) {
              next = addEdge(e, next);
            }
          }
          return next;
        });

        syncSimulation(
          newChildren.map((c, i) => ({
            id: c.track_id,
            isSeed: false,
            x: initialPositions[i].x,
            y: initialPositions[i].y,
          })),
          newEdges.map((e) => ({ source: e.source!, target: e.target! })),
          false,
        );

        setPopover(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to expand");
      } finally {
        setLoading(false);
      }
    },
    [popover, setNodes, setEdges, syncSimulation],
  );

  const handleDeleteNode = useCallback(
    (nodeId: string) => {
      const survivingEdges = edges.filter(
        (e) => e.source !== nodeId && e.target !== nodeId,
      );
      const adjacency = new Map<string, string[]>();
      for (const e of survivingEdges) {
        if (!e.source || !e.target) continue;
        const list = adjacency.get(e.source) ?? [];
        list.push(e.target);
        adjacency.set(e.source, list);
      }

      const seeds = nodes
        .filter((n) => n.id !== nodeId && n.data.isSeed)
        .map((n) => n.id);
      const reachable = new Set<string>(seeds);
      const queue = [...seeds];
      while (queue.length) {
        const cur = queue.shift()!;
        for (const next of adjacency.get(cur) ?? []) {
          if (!reachable.has(next)) {
            reachable.add(next);
            queue.push(next);
          }
        }
      }

      const removed = new Set<string>([nodeId]);
      for (const n of nodes) {
        if (n.id !== nodeId && !reachable.has(n.id)) removed.add(n.id);
      }

      setNodes((nds) => nds.filter((n) => !removed.has(n.id)));
      setEdges((eds) =>
        eds.filter((e) => !removed.has(e.source!) && !removed.has(e.target!)),
      );

      for (const id of removed) simNodesRef.current.delete(id);
      simLinksRef.current = simLinksRef.current.filter(
        (l) => !removed.has(endId(l.source)) && !removed.has(endId(l.target)),
      );
      const sim = simRef.current;
      if (sim) {
        sim.nodes(Array.from(simNodesRef.current.values()));
        sim.force<ForceLink<SimNode, SimLink>>("link")?.links(simLinksRef.current);
        sim.alpha(0.6).restart();
      }

      setPopover(null);
    },
    [nodes, edges, setNodes, setEdges],
  );

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
    if (!sn.isSeed) {
      sn.fx = null;
      sn.fy = null;
    }
    simRef.current?.alphaTarget(0);
  }, []);

  const hasGraph = nodes.length > 0;
  const trackIds = nodes.map((n) => n.id);

  return (
    <div className="h-full w-full relative overflow-hidden">
      {/* Ocean background — always present */}
      <img
        src="/ocean-bg.jpg"
        alt=""
        className="absolute inset-0 w-full h-full object-cover pointer-events-none select-none"
        draggable={false}
      />

      {hasGraph ? (
        <GraphView
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onNodeClick={handleNodeClick}
          onPaneClick={() => setPopover(null)}
          onNodeDragStart={handleNodeDragStart}
          onNodeDrag={handleNodeDrag}
          onNodeDragStop={handleNodeDragStop}
          onSeed={handleSeed}
          seedingPhase={seedingPhase}
          trackIds={trackIds}
          edgeCount={edges.length}
        />
      ) : (
        <Hero onPick={handleSeed} seedingPhase={seedingPhase} />
      )}

      {popover && (
        <div
          className="fixed z-30"
          style={{
            left: Math.min(popover.x, window.innerWidth - 320),
            top: Math.min(popover.y, window.innerHeight - 380),
          }}
        >
          <NodePopover
            key={popover.nodeId}
            nodeLabel={popover.label}
            isSeed={popover.isSeed}
            loading={loading}
            onExpand={handleExpand}
            onDelete={() => handleDeleteNode(popover.nodeId)}
            onClose={() => setPopover(null)}
          />
        </div>
      )}

      {error && (
        <div className="absolute bottom-24 left-1/2 -translate-x-1/2 z-40 overflow-hidden rounded-xl shadow-[0px_1px_4.1px_0px_rgba(0,0,0,0.25)]">
          <div aria-hidden className="absolute inset-0 backdrop-blur-[4px] bg-white/90 rounded-xl pointer-events-none" />
          <div className="relative px-4 py-2 text-sm text-red-600 flex items-center gap-3">
            {error}
            <button
              onClick={() => setError(null)}
              className="text-red-400 hover:text-red-600 transition-colors"
            >
              ×
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Graph view ────────────────────────────────────────────────────────────────

type GraphViewProps = {
  nodes: ReturnType<typeof useNodesState>[0];
  edges: ReturnType<typeof useEdgesState>[0];
  onNodesChange: ReturnType<typeof useNodesState>[1];
  onEdgesChange: ReturnType<typeof useEdgesState>[1];
  onNodeClick: NodeMouseHandler;
  onPaneClick: () => void;
  onNodeDragStart?: NodeDragHandler;
  onNodeDrag?: NodeDragHandler;
  onNodeDragStop?: NodeDragHandler;
  onSeed: (song: SongSearchResult) => void;
  seedingPhase: SeedingPhase;
  trackIds: string[];
  edgeCount: number;
};

function GraphView({
  nodes,
  edges,
  onNodesChange,
  onEdgesChange,
  onNodeClick,
  onPaneClick,
  onNodeDragStart,
  onNodeDrag,
  onNodeDragStop,
  onSeed,
  seedingPhase,
  trackIds,
  edgeCount,
}: GraphViewProps) {
  return (
    <>
      {/* Full-screen graph canvas */}
      <div className="absolute inset-0">
        <Graph
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onNodeClick={onNodeClick}
          onPaneClick={onPaneClick}
          onNodeDragStart={onNodeDragStart}
          onNodeDrag={onNodeDrag}
          onNodeDragStop={onNodeDragStop}
        />
      </div>

      {/* pyo logo — top-left, partially above viewport like in the design */}
      <div
        className="absolute left-[26px] pointer-events-none z-10"
        style={{ top: -27 }}
      >
        <span
          className="font-display font-medium text-[120px] text-white/75 leading-none select-none"
          style={{ textShadow: "0px 1px 4.1px rgba(0,0,0,0.25)" }}
        >
          pyo
        </span>
      </div>

      {/* Graph Info — top-right */}
      <div className="absolute right-5 top-[29px] z-10">
        <GraphInfo
          nodeCount={nodes.length}
          edgeCount={edgeCount}
          trackIds={trackIds}
        />
      </div>

      {/* Search bar + seeding status — bottom-center */}
      <div className="absolute bottom-8 left-1/2 -translate-x-1/2 z-10 w-[430px] max-w-[calc(100%-80px)]">
        {seedingPhase && (
          <div className="mb-2 flex justify-center">
            <SeedingStatus phase={seedingPhase} compact />
          </div>
        )}
        <SearchBar
          onPick={onSeed}
          placeholder="Start typing to add more sources to the graph."
          dropUp
        />
      </div>
    </>
  );
}

// ── Home / Hero ───────────────────────────────────────────────────────────────

function Hero({
  onPick,
  seedingPhase,
}: {
  onPick: (song: SongSearchResult) => void;
  seedingPhase: SeedingPhase;
}) {
  return (
    <div
      className="absolute flex flex-col items-start fade-up"
      style={{ left: 60, top: "38%" }}
    >
      <span
        className="font-display font-medium text-[128px] text-white leading-none select-none"
        style={{ textShadow: "0px 2px 8px rgba(0,0,0,0.18)" }}
      >
        pyo
      </span>
      <p
        className="text-white text-[17px] leading-normal mt-3 font-light"
        style={{ textShadow: "0px 1px 4px rgba(0,0,0,0.3)" }}
      >
        stands for &ldquo;putting you on&rdquo; good music.
      </p>
      <div className="mt-6 w-[430px] max-w-[calc(100vw-80px)]">
        <SearchBar
          onPick={onPick}
          placeholder="Tell us what you like, and we'll find similar."
          autoFocus
        />
        {seedingPhase && <SeedingStatus phase={seedingPhase} className="mt-3" />}
      </div>
    </div>
  );
}

// ── Seeding status indicator ──────────────────────────────────────────────────

function SeedingStatus({
  phase,
  className = "",
  compact = false,
}: {
  phase: SeedingPhase;
  className?: string;
  compact?: boolean;
}) {
  if (!phase) return null;

  const label =
    phase === "checking" ? "Checking song" : "Building your graph";

  return (
    <div className={`flex flex-col items-start gap-2 ${className}`}>
      <div className="relative overflow-hidden rounded-full shadow-[0px_1px_4.1px_rgba(0,0,0,0.25)]">
        <div aria-hidden className="absolute inset-0 backdrop-blur-[3px] bg-white/[0.22] pointer-events-none rounded-full" />
        <div
          className={`relative flex items-center gap-2.5 text-white ${compact ? "text-xs px-3 py-1.5" : "text-sm px-4 py-2"} font-medium`}
          style={{ textShadow: "0px 1px 3px rgba(0,0,0,0.4)" }}
        >
          <Spinner size={compact ? 13 : 15} className="text-white" />
          <span>{label}</span>
        </div>
      </div>
      {phase === "cold" && (
        <div
          className={`text-white/80 ${compact ? "text-[11px]" : "text-xs"} font-medium pl-1`}
          style={{ textShadow: "0px 1px 3px rgba(0,0,0,0.5)" }}
        >
          First time — fetching from Last.fm, may take 30+ sec.
        </div>
      )}
    </div>
  );
}
