import { z } from "zod";

export const taskDragIdsSchema = z.array(z.string().min(1)).min(1);
