import { useCallback, useRef, useState } from "react";
import { ShapeGrid } from "./components/ShapeGrid";
import {
  addEdge,
  useEdgesState,
  useNodesState,
  type Edge,
  type Node,
  type NodeMouseHandler,
} from "reactflow";
import { GraphView } from "./components/GraphView";
import { Hero } from "./components/Hero";
import { NodePopover } from "./components/NodePopover";
import { SeedingStatus } from "./components/SeedingStatus";
import { type SongNodeData } from "./components/SongNode";
import { type GraphHandle } from "./components/Graph";
import { expandFromTrack, getSongStatus, seedSong } from "./api";
import { useGraphSim } from "./hooks/useGraphSim";
import type { ExpansionParams, SongSearchResult } from "./types";

type SeedingPhase = null | "checking" | "warm" | "cold";

type Vec = { x: number; y: number };

const ARC_RADIUS = 260;
const STAGGER_MS = 55;

function arcAround(count: number, parentPos: Vec): Vec[] {
  const arcStart = -Math.PI * 0.85;
  const arcEnd = Math.PI * 0.85;
  return Array.from({ length: count }, (_, i) => {
    const t = count === 1 ? 0.5 : i / (count - 1);
    const angle = arcStart + (arcEnd - arcStart) * t;
    return {
      x: parentPos.x + ARC_RADIUS * Math.sin(angle),
      y: parentPos.y + ARC_RADIUS * (0.4 + 0.6 * Math.cos(angle)),
    };
  });
}

type PopoverState = { nodeId: string; label: string; isSeed: boolean; x: number; y: number };

export default function App() {
  const [nodes, setNodes, onNodesChange] = useNodesState<SongNodeData>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [popover, setPopover] = useState<PopoverState | null>(null);
  const [loading, setLoading] = useState(false);
  const [seedingPhase, setSeedingPhase] = useState<SeedingPhase>(null);
  const [error, setError] = useState<string | null>(null);

  const graphRef = useRef<GraphHandle>(null);

  const { simNodesRef, syncSimulation, removeNodesFromSim, handleNodeDragStart, handleNodeDrag, handleNodeDragStop } =
    useGraphSim(setNodes);

  // ── Seed a song ──────────────────────────────────────────────────────────────

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
          // non-fatal
        }
        setSeedingPhase(cached ? "warm" : "cold");

        const isFirstSeed = simNodesRef.current.size === 0;

        await seedSong(song.track_id);
        const initialChildren = await expandFromTrack(song.track_id, "recommendations", {
          k: 8, lambda: 0.7, niche: false, maxDepth: 3, excludeIds: [],
        });

        let seedPos: Vec;
        if (isFirstSeed) {
          seedPos = { x: 0, y: 0 };
        } else {
          const existingSim = simNodesRef.current.get(song.track_id);
          if (existingSim) {
            seedPos = { x: existingSim.x ?? 0, y: existingSim.y ?? 0 };
          } else {
            const maxX = Math.max(...Array.from(simNodesRef.current.values()).map((n) => n.x ?? 0), 0);
            seedPos = { x: maxX + 600, y: 0 };
          }
        }

        const childPositions = arcAround(initialChildren.length, seedPos);

        const seedNode: Node<SongNodeData> = {
          id: song.track_id,
          type: "song",
          position: seedPos,
          data: { name: song.name, artist: song.artist, image: song.image, isSeed: true },
        };

        const newChildNodes: Node<SongNodeData>[] = initialChildren
          .filter((c) => !simNodesRef.current.has(c.track_id))
          .map((c, i) => ({
            id: c.track_id,
            type: "song",
            position: childPositions[i],
            data: { name: c.name, artist: c.artist, image: c.image, isSeed: false, similarity: c.similarity, listeners: c.listeners },
          }));

        const newEdges: Edge[] = initialChildren.map((c) => ({
          id: `${song.track_id}->${c.track_id}`,
          source: song.track_id,
          target: c.track_id,
        }));

        // Seed appears immediately
        if (isFirstSeed) {
          setNodes([seedNode]);
          setEdges([]);
          syncSimulation([{ id: song.track_id, isSeed: true, x: seedPos.x, y: seedPos.y }], [], true);
        } else {
          setNodes((nds) => {
            const base = nds.some((n) => n.id === song.track_id)
              ? nds.map((n) => n.id === song.track_id ? { ...n, data: { ...n.data, isSeed: true } } : n)
              : [...nds, seedNode];
            return base;
          });
          if (!simNodesRef.current.has(song.track_id)) {
            syncSimulation([{ id: song.track_id, isSeed: true, x: seedPos.x, y: seedPos.y }], [], false);
          } else {
            const sn = simNodesRef.current.get(song.track_id)!;
            sn.fx = seedPos.x;
            sn.fy = seedPos.y;
          }
        }

        // Children stagger in one by one
        newChildNodes.forEach((node, i) => {
          const edge = newEdges.find((e) => e.target === node.id);
          setTimeout(() => {
            setNodes((nds) => [...nds, node]);
            if (edge) setEdges((eds) => addEdge(edge, eds));
            syncSimulation(
              [{ id: node.id, isSeed: false, x: node.position.x, y: node.position.y }],
              edge ? [{ source: String(edge.source), target: node.id }] : [],
              false,
            );
          }, STAGGER_MS * (i + 1));
        });

        if (!isFirstSeed) {
          setTimeout(() => graphRef.current?.fitView(), STAGGER_MS * (newChildNodes.length + 3));
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to seed song");
      } finally {
        setSeedingPhase(null);
      }
    },
    [setNodes, setEdges, syncSimulation, simNodesRef],
  );

  // ── Expand from a node ───────────────────────────────────────────────────────

  const handleExpand = useCallback(
    async (params: ExpansionParams) => {
      if (!popover) return;
      setLoading(true);
      setError(null);
      try {
        const parentId = popover.nodeId;
        const knownIds = Array.from(simNodesRef.current.keys());
        const excludeIds = params.allowDuplicates ? [] : knownIds.filter((id) => id !== parentId);
        const children = await expandFromTrack(parentId, params.method, {
          k: params.k, lambda: params.lambda, niche: params.niche,
          maxDepth: params.maxDepth, excludeIds,
        });

        const parentSim = simNodesRef.current.get(parentId);
        const parentPos: Vec = { x: parentSim?.x ?? 0, y: parentSim?.y ?? 0 };

        const newChildren = children.filter((c) => !simNodesRef.current.has(c.track_id));
        const initialPositions = arcAround(newChildren.length, parentPos);

        const newNodes: Node<SongNodeData>[] = newChildren.map((c, i) => ({
          id: c.track_id,
          type: "song",
          position: initialPositions[i],
          data: { name: c.name, artist: c.artist, image: c.image, isSeed: false, similarity: c.similarity, listeners: c.listeners },
        }));

        const newEdges: Edge[] = children.map((c) => ({
          id: `${parentId}->${c.track_id}`,
          source: parentId,
          target: c.track_id,
        }));

        // Edges to already-present nodes go in immediately
        const edgesForExisting = newEdges.filter((e) => !newNodes.some((n) => n.id === e.target));
        if (edgesForExisting.length > 0) {
          setEdges((eds) => {
            let next = eds;
            for (const e of edgesForExisting) {
              if (!next.some((ex) => ex.id === e.id)) next = addEdge(e, next);
            }
            return next;
          });
        }

        // New nodes stagger in one by one
        newNodes.forEach((node, i) => {
          const edge = newEdges.find((e) => e.target === node.id);
          setTimeout(() => {
            setNodes((nds) => [...nds, node]);
            if (edge) setEdges((eds) => addEdge(edge, eds));
            syncSimulation(
              [{ id: node.id, isSeed: false, x: node.position.x, y: node.position.y }],
              edge ? [{ source: String(edge.source), target: node.id }] : [],
              false,
            );
          }, STAGGER_MS * i);
        });

        setPopover(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to expand");
      } finally {
        setLoading(false);
      }
    },
    [popover, setNodes, setEdges, syncSimulation, simNodesRef],
  );

  // ── Delete a node ────────────────────────────────────────────────────────────

  const handleDeleteNode = useCallback(
    (nodeId: string) => {
      const survivingEdges = edges.filter((e) => e.source !== nodeId && e.target !== nodeId);
      const adjacency = new Map<string, string[]>();
      for (const e of survivingEdges) {
        if (!e.source || !e.target) continue;
        const list = adjacency.get(e.source) ?? [];
        list.push(e.target);
        adjacency.set(e.source, list);
      }

      const seeds = nodes.filter((n) => n.id !== nodeId && n.data.isSeed).map((n) => n.id);
      const reachable = new Set<string>(seeds);
      const queue = [...seeds];
      while (queue.length) {
        const cur = queue.shift()!;
        for (const next of adjacency.get(cur) ?? []) {
          if (!reachable.has(next)) { reachable.add(next); queue.push(next); }
        }
      }

      const removed = new Set<string>([nodeId]);
      for (const n of nodes) {
        if (n.id !== nodeId && !reachable.has(n.id)) removed.add(n.id);
      }

      setNodes((nds) => nds.filter((n) => !removed.has(n.id)));
      setEdges((eds) => eds.filter((e) => !removed.has(e.source!) && !removed.has(e.target!)));

      removeNodesFromSim(removed);
      setPopover(null);
    },
    [nodes, edges, setNodes, setEdges, removeNodesFromSim],
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

  const hasGraph = nodes.length > 0;

  return (
    <div className="h-full w-full relative overflow-hidden bg-[#42a7f5]">
      <div className="absolute inset-0">
        <ShapeGrid
          direction="diagonal"
          speed={0.5}
          borderColor="rgba(255,255,255,0.08)"
          hoverFillColor="rgba(255,255,255,0.00)"
          squareSize={44}
          hoverTrailAmount={0}
        />
      </div>
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
          trackIds={nodes.map((n) => n.id)}
          edgeCount={edges.length}
          graphRef={graphRef}
        />
      ) : (
        <Hero onPick={handleSeed} disabled={!!seedingPhase} />
      )}

      {/* Full-screen frosted overlay while seeding from the hero page */}
      {!hasGraph && seedingPhase && (
        <div className="absolute inset-0 z-50 flex items-center justify-center">
          <div aria-hidden className="absolute inset-0 backdrop-blur-sm bg-black/20 pointer-events-none" />
          <div className="relative">
            <SeedingStatus phase={seedingPhase} />
          </div>
        </div>
      )}

      {popover && (
        <div
          className="fixed z-30"
          style={{
            left: Math.min(popover.x, window.innerWidth - 320),
            top: Math.min(popover.y, window.innerHeight - 400),
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
            <button onClick={() => setError(null)} className="text-red-400 hover:text-red-600 transition-colors">
              ×
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
