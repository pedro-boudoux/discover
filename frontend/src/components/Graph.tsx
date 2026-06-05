import { useMemo } from "react";
import ReactFlow, {
  type DefaultEdgeOptions,
  type Edge,
  type Node,
  type NodeDragHandler,
  type NodeMouseHandler,
  type NodeTypes,
  type OnEdgesChange,
  type OnNodesChange,
  Panel,
} from "reactflow";
import "reactflow/dist/style.css";
import { SongNode, type SongNodeData } from "./SongNode";
import { ZoomControls } from "./ZoomControls";

const defaultEdgeOptions: DefaultEdgeOptions = {
  type: "simplebezier",
  style: { stroke: "rgba(255,255,255,0.5)", strokeWidth: 1.5, opacity: 0.8 },
};

type Props = {
  nodes: Node<SongNodeData>[];
  edges: Edge[];
  onNodesChange: OnNodesChange;
  onEdgesChange: OnEdgesChange;
  onNodeClick: NodeMouseHandler;
  onPaneClick: () => void;
  onNodeDragStart?: NodeDragHandler;
  onNodeDrag?: NodeDragHandler;
  onNodeDragStop?: NodeDragHandler;
};

export function Graph({
  nodes,
  edges,
  onNodesChange,
  onEdgesChange,
  onNodeClick,
  onPaneClick,
  onNodeDragStart,
  onNodeDrag,
  onNodeDragStop,
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
      onNodeDragStart={onNodeDragStart}
      onNodeDrag={onNodeDrag}
      onNodeDragStop={onNodeDragStop}
      nodeTypes={nodeTypes}
      nodeOrigin={[0.5, 0.5]}
      defaultEdgeOptions={defaultEdgeOptions}
      fitView
      fitViewOptions={{ padding: 0.3, duration: 400 }}
      proOptions={{ hideAttribution: true }}
      minZoom={0.2}
      maxZoom={1.6}
    >
      <Panel position="bottom-left" className="!m-0 !ml-[26px] !mb-8">
        <ZoomControls />
      </Panel>
    </ReactFlow>
  );
}
