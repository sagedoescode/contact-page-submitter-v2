// src/hooks/useCampaignWebSocket.js
import { useEffect, useState } from "react";

export const useCampaignWebSocket = (campaignId) => {
  const [stats, setStats] = useState(null);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    if (!campaignId) return;

    const ws = new WebSocket(
      `ws://localhost:8000/api/ws/campaign/${campaignId}`
    );

    ws.onopen = () => {
      setConnected(true);
      console.log("WebSocket connected");
    };

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      setStats(data);
    };

    ws.onclose = () => {
      setConnected(false);
      console.log("WebSocket disconnected");
    };

    return () => {
      ws.close();
    };
  }, [campaignId]);

  return { stats, connected };
};
