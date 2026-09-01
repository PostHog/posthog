import { CyclotronInternalPoolConfig, CyclotronPoolConfig } from './types';
export declare function convertToInternalPoolConfig(poolConfig: CyclotronPoolConfig): CyclotronInternalPoolConfig;
export declare function serializeObject(name: string, obj: Record<string, any> | null): string | null;
export declare function deserializeObject(name: string, str: any): Record<string, any> | null;
