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
    return () => {
      sim.stop();
    };
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
        const node: SimNode = {
          id: n.id,
          isSeed: n.isSeed,
          x: n.x,
          y: n.y,
        };
        if (n.isSeed) {
          node.fx = 0;
          node.fy = 0;
        }
        simNodesRef.current.set(n.id, node);
      }

      const linkKey = (l: SimLink) => {
        const s =
          typeof l.source === "string"
            ? l.source
            : (l.source as SimNode).id;
        const t =
          typeof l.target === "string"
            ? l.target
            : (l.target as SimNode).id;
        return `${s}->${t}`;
      };
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

        await seedSong(song.track_id);
        const initialChildren = await expandFromTrack(
          song.track_id,
          "recommendations",
          { k: 8, lambda: 0.7, niche: false, maxDepth: 3, excludeIds: [] },
        );

        const seedPos = { x: 0, y: 0 };
        const childPositions = arcAround(initialChildren.length, seedPos);

        const seedNode: Node<SongNodeData> = {
          id: song.track_id,
          type: "song",
          position: seedPos,
          data: {
            name: song.name,
            artist: song.artist,
            image: song.image,
            isSeed: true,
          },
        };

        const childNodes: Node<SongNodeData>[] = initialChildren.map((c, i) => ({
          id: c.track_id,
          type: "song",
          position: childPositions[i],
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

        setNodes([seedNode, ...childNodes]);
        setEdges(newEdges);

        syncSimulation(
          [
            { id: song.track_id, isSeed: true, x: 0, y: 0 },
            ...initialChildren.map((c, i) => ({
              id: c.track_id,
              isSeed: false,
              x: childPositions[i].x,
              y: childPositions[i].y,
            })),
          ],
          newEdges.map((e) => ({ source: e.source!, target: e.target! })),
          true,
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
        const parentPos: Vec = {
          x: parentSim?.x ?? 0,
          y: parentSim?.y ?? 0,
        };

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

  return (
    <div className="h-full w-full relative">
      {hasGraph ? (
        <>
          <Graph
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onNodeClick={handleNodeClick}
            onPaneClick={() => setPopover(null)}
            onNodeDragStart={handleNodeDragStart}
            onNodeDrag={handleNodeDrag}
            onNodeDragStop={handleNodeDragStop}
          />
          <div className="absolute top-3 left-3 z-10 w-[420px] max-w-[calc(100%-1.5rem)]">
            <SearchBar
              onPick={handleSeed}
              placeholder="Search another song to reseed…"
            />
            {seedingPhase && (
              <SeedingStatus phase={seedingPhase} className="mt-2" compact />
            )}
          </div>
        </>
      ) : (
        <Hero onPick={handleSeed} seedingPhase={seedingPhase} />
      )}

      {popover && (
        <div
          className="fixed z-30"
          style={{
            left: Math.min(popover.x, window.innerWidth - 340),
            top: Math.min(popover.y, window.innerHeight - 360),
          }}
        >
          <NodePopover
            nodeLabel={popover.label}
            loading={loading}
            onExpand={handleExpand}
            onClose={() => setPopover(null)}
          />
        </div>
      )}

      {error && (
        <div className="absolute bottom-4 left-1/2 -translate-x-1/2 z-40 bg-red-950 border border-red-900 text-red-200 text-sm rounded-md px-4 py-2 shadow-2xl">
          {error}
          <button
            onClick={() => setError(null)}
            className="ml-3 text-red-300 hover:text-white"
          >
            ×
          </button>
        </div>
      )}
    </div>
  );
}

function Hero({
  onPick,
  seedingPhase,
}: {
  onPick: (song: SongSearchResult) => void;
  seedingPhase: SeedingPhase;
}) {
  return (
    <div className="h-full w-full flex flex-col items-center justify-center px-6">
      <div className="text-center mb-8">
        <h1 className="text-4xl md:text-5xl font-medium tracking-tight mb-3">
          Underground music, as a graph.
        </h1>
        <p className="text-muted max-w-md mx-auto">
          Drop a song. We'll find sonic neighbors you've never heard. Every
          recommendation becomes a node you can keep exploring.
        </p>
      </div>
      <SearchBar onPick={onPick} autoFocus />
      {seedingPhase && <SeedingStatus phase={seedingPhase} className="mt-5" />}
    </div>
  );
}

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
    phase === "checking"
      ? "Checking song"
      : phase === "warm"
        ? "Building your graph"
        : "Building your graph";

  return (
    <div className={`flex flex-col items-start gap-1 ${className}`}>
      <div
        className={`flex items-center gap-2 text-muted ${
          compact ? "text-xs" : "text-sm"
        }`}
      >
        <Spinner size={compact ? 12 : 14} className="text-accent" />
        <LoadingText text={label} />
      </div>
      {phase === "cold" && (
        <div
          className={`text-amber-300/90 ${
            compact ? "text-[11px]" : "text-xs"
          } pl-5`}
        >
          First time seeing this song — fetching tags from Last.fm. This may take
          30+ seconds.
        </div>
      )}
    </div>
  );
}
