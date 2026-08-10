import { createContext, useContext } from "react";

import type { RuntimeMeta } from "./api";

export const defaultRuntime: RuntimeMeta = {
  environment: "unconfirmed",
  read_only: true,
  data_mode: "synthetic-demo",
  label: "正在确认运行模式 · 暂时只读",
};

export const RuntimeContext = createContext<RuntimeMeta>(defaultRuntime);

export function useRuntime() {
  return useContext(RuntimeContext);
}
