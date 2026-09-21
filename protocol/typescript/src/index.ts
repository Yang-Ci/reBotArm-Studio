export type ProductAvailability = 'supported' | 'planned' | 'disabled';

export interface ProductDefinition {
  id: string;
  displayName: string;
  family: string;
  availability: ProductAvailability;
  driver: string;
  transport: {
    kind: string;
    defaultChannel: string;
    bitrate?: number;
  };
  joints: string[];
  capabilities: string[];
  assets: {
    robotModel: string;
    mujocoModel: string;
  };
}

export type RuntimeMode = 'hardware' | 'simulation';

export interface ProductSelection {
  productId: string;
  mode: RuntimeMode;
}

