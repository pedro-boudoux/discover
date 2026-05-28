import { useMemo } from "react";
import ReactFlow, {
  Background,
  Controls,
  type Edge,
  type Node,
  type NodeMouseHandler,
  type NodeTypes,
  type OnEdgesChange,
  type OnNodesChange,
  Panel,
} from "reactflow";
import "reactflow/dist/style.css";
import { SongNode, type SongNodeData } from "./SongNode";

type Props = {
  nodes: Node<SongNodeData>[];
  edges: Edge[];
  onNodesChange: OnNodesChange;
  onEdgesChange: OnEdgesChange;
  onNodeClick: NodeMouseHandler;
  onPaneClick: () => void;
};

export function Graph({
  nodes,
  edges,
  onNodesChange,
  onEdgesChange,
  onNodeClick,
  onPaneClick,
}: Props) {
  const nodeTypes = useMemo<NodeTypes>(() => ({ song: SongNode }), []);

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      onNodesChange={onNodesChange}
      onEdgesChange={onEdgesChange}
      onNodeClick={onNodeClick}
      onPaneClick={onPaneClick}
      nodeTypes={nodeTypes}
      fitView
      fitViewOptions={{ padding: 0.3, duration: 400 }}
      proOptions={{ hideAttribution: true }}
      minZoom={0.2}
      maxZoom={1.6}
    >
      <Background color="#1f1f1f" gap={28} size={1} />
      <Controls
        className="!bg-canvas !border !border-edge"
        showInteractive={false}
      />
      <Panel position="top-right" className="!m-3">
        <Legend nodeCount={nodes.length} edgeCount={edges.length} />
      </Panel>
    </ReactFlow>
  );
}

function Legend({ nodeCount, edgeCount }: { nodeCount: number; edgeCount: number }) {
  return (
    <div className="bg-canvas/80 backdrop-blur border border-edge rounded-md px-3 py-1.5 text-xs text-muted tabular-nums">
      {nodeCount} nodes · {edgeCount} edges
    </div>
  );
}
