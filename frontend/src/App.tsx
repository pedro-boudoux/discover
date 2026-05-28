import { useCallback, useRef, useState } from "react";
import {
  addEdge,
  useEdgesState,
  useNodesState,
  type Edge,
  type Node,
  type NodeMouseHandler,
} from "reactflow";
import { Graph } from "./components/Graph";
import { NodePopover } from "./components/NodePopover";
import { SearchBar } from "./components/SearchBar";
import type { SongNodeData } from "./components/SongNode";
import { expandFromTrack, getSongStatus, seedSong } from "./api";
import { LoadingText, Spinner } from "./components/Loader";
import type { ExpansionParams, SongSearchResult } from "./types";

type SeedingPhase = null | "checking" | "warm" | "cold";

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
  const nodePositions = useRef(new Map<string, { x: number; y: number }>());

  const placeChildrenAround = useCallback(
    (count: number, parentPos: { x: number; y: number }) => {
      const radius = 320;
      const arcStart = -Math.PI * 0.85;
      const arcEnd = Math.PI * 0.85;
      const positions: { x: number; y: number }[] = [];
      for (let i = 0; i < count; i++) {
        const t = count === 1 ? 0.5 : i / (count - 1);
        const angle = arcStart + (arcEnd - arcStart) * t;
        positions.push({
          x: parentPos.x + radius * Math.sin(angle),
          y: parentPos.y + radius * (0.4 + 0.6 * Math.cos(angle)),
        });
      }
      return positions;
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
          { k: 8, lambda: 0.7, niche: false, maxDepth: 3 },
        );

        const seedNode: Node<SongNodeData> = {
          id: song.track_id,
          type: "song",
          position: { x: 0, y: 0 },
          data: {
            name: song.name,
            artist: song.artist,
            image: song.image,
            isSeed: true,
          },
        };
        nodePositions.current.clear();
        nodePositions.current.set(song.track_id, { x: 0, y: 0 });

        const childPositions = placeChildrenAround(initialChildren.length, {
          x: 0,
          y: 0,
        });

        const childNodes: Node<SongNodeData>[] = initialChildren.map((c, i) => {
          nodePositions.current.set(c.track_id, childPositions[i]);
          return {
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
          };
        });

        const newEdges: Edge[] = initialChildren.map((c) => ({
          id: `${song.track_id}->${c.track_id}`,
          source: song.track_id,
          target: c.track_id,
        }));

        setNodes([seedNode, ...childNodes]);
        setEdges(newEdges);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to seed song");
      } finally {
        setSeedingPhase(null);
      }
    },
    [placeChildrenAround, setNodes, setEdges],
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
        const children = await expandFromTrack(parentId, params.method, {
          k: params.k,
          lambda: params.lambda,
          niche: params.niche,
          maxDepth: params.maxDepth,
        });

        const parentPos =
          nodePositions.current.get(parentId) ?? { x: 0, y: 0 };

        const newChildren = children.filter(
          (c) => !nodePositions.current.has(c.track_id),
        );

        const childPositions = placeChildrenAround(
          newChildren.length,
          parentPos,
        );

        const newNodes: Node<SongNodeData>[] = newChildren.map((c, i) => {
          nodePositions.current.set(c.track_id, childPositions[i]);
          return {
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
          };
        });

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
        setPopover(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to expand");
      } finally {
        setLoading(false);
      }
    },
    [popover, placeChildrenAround, setNodes, setEdges],
  );

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
