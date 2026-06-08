import { forwardRef, useImperativeHandle, useMemo, useRef } from "react";
import ReactFlow, {
  type DefaultEdgeOptions,
  type Edge,
  type Node,
  type NodeDragHandler,
  type NodeMouseHandler,
  type NodeTypes,
  type OnEdgesChange,
  type OnNodesChange,
  type ReactFlowInstance,
  Panel,
} from "reactflow";
import "reactflow/dist/style.css";
import { SongNode, type SongNodeData } from "./SongNode";
import { ZoomControls } from "./ZoomControls";

const defaultEdgeOptions: DefaultEdgeOptions = {
  type: "simplebezier",
  style: { stroke: "rgba(255,255,255,0.5)", strokeWidth: 1.5, opacity: 0.8 },
};

export type GraphHandle = { fitView: () => void };

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

export const Graph = forwardRef<GraphHandle, Props>(function Graph({
  nodes,
  edges,
  onNodesChange,
  onEdgesChange,
  onNodeClick,
  onPaneClick,
  onNodeDragStart,
  onNodeDrag,
  onNodeDragStop,
}, ref) {
  const nodeTypes = useMemo<NodeTypes>(() => ({ song: SongNode }), []);
  const rfInstanceRef = useRef<ReactFlowInstance | null>(null);

  useImperativeHandle(ref, () => ({
    fitView: () => rfInstanceRef.current?.fitView({ padding: 0.3, duration: 600 }),
  }));

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
      onInit={(inst) => { rfInstanceRef.current = inst; }}
    >
      <Panel position="bottom-left" className="!m-0 !ml-5 !mb-8">
        <ZoomControls />
      </Panel>
    </ReactFlow>
  );
});
