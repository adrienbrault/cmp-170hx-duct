/* SPDX-License-Identifier: GPL-3.0-or-later
 * Spatially coupled fin/base model for OpenFOAM 2606.
 * Fluid: div(phi,T)-div(alpha grad T) = Hvol/(rho cp)*(Tb-T).
 * Base: -k*t*laplacian_2D(Tb)+integral_x Hvol*(Tb-T) dx = q''.
 * Fin efficiency is a closure supplied in thermalProperties, not resolved fins.
 * Energy exchange uses the identical volume weights on both sides.
 * pathHvol supplies one h*a per port (main, lower side, upper side).
 * Absent pathHvol preserves legacy Hvol on path0 only.
 * Optional thermalProperties: maxCouplingIterations (1000), couplingRelaxation (0.7).
 */
#include "fvCFD.H"
#include "timeSelector.H"
#include <fstream>
#include <iomanip>
#include <vector>
#include <cmath>
#include <array>
int main(int argc,char *argv[])
{
 timeSelector::addOptions();
 #include "setRootCase.H"
 #include "createTime.H"
 instantList times=timeSelector::select0(runTime,args);runTime.setTime(times.last(),times.size()-1);
 #include "createMesh.H"
 if(Pstream::parRun())FatalErrorInFunction<<"Run chtFinBase serially on the reconstructed mesh"<<exit(FatalError);
 IOdictionary props(IOobject("thermalProperties",runTime.constant(),mesh,IOobject::MUST_READ,IOobject::NO_WRITE));
 const int ny=props.get<label>("ny"),nz=props.get<label>("nz"),nb=ny*nz,nb2=2*nb;
 const scalar z0=props.get<scalar>("cardStart"),len=props.get<scalar>("cardLength"),w=.0948;
 const scalar inletT=props.get<scalar>("inletT"),P=props.get<scalar>("power"),rhoCp=props.get<scalar>("rhoCp");
 const scalar k=props.get<scalar>("copperK"),thick=props.get<scalar>("baseThickness"),Hv=props.get<scalar>("Hvol");
 scalarList pathHvol(3,0);pathHvol[0]=Hv;
 if(props.found("pathHvol"))pathHvol=props.get<scalarList>("pathHvol");
 if(pathHvol.empty())FatalErrorInFunction<<"pathHvol must contain at least the main path"<<exit(FatalError);
 for(const scalar h:pathHvol)if(!std::isfinite(h)||h<0)FatalErrorInFunction<<"pathHvol must be finite and nonnegative"<<exit(FatalError);
 const scalar sourceCentre=props.getOrDefault<scalar>("sourceCentre",.48),sy=props.getOrDefault<scalar>("sourceSigmaY",.021),sz=props.getOrDefault<scalar>("sourceSigmaZ",.030),uniformPart=props.getOrDefault<scalar>("uniformHeatFraction",.2);
 const label maxCouplingIterations=props.getOrDefault<label>("maxCouplingIterations",1000);
 const scalar couplingRelaxation=props.getOrDefault<scalar>("couplingRelaxation",.7);
 // Card exit flux seam: the one place that names the per-card exit. Swap for faceZones
 // cardExit0/1 once the case builder writes them.
 const word cardExitPatch[2]={"outletLeft","outletRight"};
 const scalar dy=w/ny,dz=len/nz,Gy=k*thick*dz/dy,Gz=k*thick*dy/dz;
 volVectorField U(IOobject("U",runTime.timeName(),mesh,IOobject::MUST_READ,IOobject::NO_WRITE),mesh);
 surfaceScalarField phi(IOobject("phi",runTime.timeName(),mesh,IOobject::MUST_READ,IOobject::NO_WRITE),mesh);
 word tTime=isFile(runTime.path()/runTime.timeName()/"T")?runTime.timeName():word("0");
 volScalarField T(IOobject("T",tTime,mesh,IOobject::MUST_READ,IOobject::NO_WRITE),mesh);
 volScalarField nut(IOobject("nut",runTime.timeName(),mesh,IOobject::READ_IF_PRESENT,IOobject::NO_WRITE),mesh,dimensionedScalar(dimViscosity,0));
 volScalarField H(IOobject("H",runTime.timeName(),mesh,IOobject::NO_READ,IOobject::AUTO_WRITE),mesh,dimensionedScalar(dimless/dimTime,0));
 volScalarField Tb(IOobject("Tb",runTime.timeName(),mesh,IOobject::NO_READ,IOobject::AUTO_WRITE),mesh,dimensionedScalar(dimTemperature,inletT));
 volScalarField alpha(IOobject("alpha",runTime.timeName(),mesh,IOobject::NO_READ,IOobject::NO_WRITE),mesh,dimensionedScalar(dimViscosity,2.16e-5));
 labelList cellPath(mesh.nCells(),-1);scalarField cellHv(mesh.nCells(),0);
 labelList bin(mesh.nCells(),-1);scalarField Hsum(nb2,0),HT(nb2,0),base(nb2,inletT+50),q(nb2,0),M(9*nb2,0);
 scalar partitionError=0,projectionError=0;
 std::vector<std::array<int,4>> ids(mesh.nCells(),std::array<int,4>{-1,-1,-1,-1});
 std::vector<std::array<scalar,4>> weights(mesh.nCells(),std::array<scalar,4>{0,0,0,0});
 forAll(mesh.C(),i)alpha[i]=2.16e-5+max(scalar(0),nut[i])/.85;
 for(int card=0;card<2;card++)
 {
  scalar cardConductance=0;
  forAll(pathHvol,path)
  {
  word zone="card"+Foam::name(card)+"path"+Foam::name(path);label zi=mesh.cellZones().findZoneID(zone);
  if(zi<0){if(path==0||pathHvol[path]>0)FatalErrorInFunction<<"Missing thermal cell zone "<<zone<<exit(FatalError);continue;}
  const auto& cells=mesh.cellZones()[zi];
  if(pathHvol[path]>0&&cells.empty())FatalErrorInFunction<<"Empty thermal cell zone "<<zone<<exit(FatalError);
  forAll(cells,j)
  {
   label i=cells[j];int iy=min(ny-1,max(0,int((mesh.C()[i].y()+w/2)/dy)));int iz=min(nz-1,max(0,int((mesh.C()[i].z()-z0)/dz)));
   if(cellPath[i]>=0)FatalErrorInFunction<<"Overlapping thermal zones at cell "<<i<<exit(FatalError);
   int b=card*nb+iz*ny+iy;bin[i]=b;cellPath[i]=path;cellHv[i]=pathHvol[path];H[i]=cellHv[i]/rhoCp;
   // Unresolved channel transfer supplies the porous-passage thermal closure.
   alpha[i]=2.16e-5;
   scalar yy=(mesh.C()[i].y()+w/2)/dy-.5,zz=(mesh.C()[i].z()-z0)/dz-.5;
   int yb=int(std::floor(yy)),zb=int(std::floor(zz));scalar fy=yy-yb,fz=zz-zb;
   if(yb<0){yb=0;fy=0;}if(yb>=ny-1){yb=ny-1;fy=0;}
   if(zb<0){zb=0;fz=0;}if(zb>=nz-1){zb=nz-1;fz=0;}
   ids[i]={card*nb+zb*ny+yb,card*nb+zb*ny+min(ny-1,yb+1),card*nb+min(nz-1,zb+1)*ny+yb,card*nb+min(nz-1,zb+1)*ny+min(ny-1,yb+1)};
   weights[i]={(1-fy)*(1-fz),fy*(1-fz),(1-fy)*fz,fy*fz};
   scalar sw=0,py=0,pz=0;for(int a=0;a<4;a++){sw+=weights[i][a];int id=ids[i][a]%nb;py+=weights[i][a]*((id%ny+.5)*dy-w/2);pz+=weights[i][a]*(z0+(id/ny+.5)*dz);}
   partitionError=max(partitionError,mag(sw-1));
   if(yy>=0&&yy<=ny-1&&zz>=0&&zz<=nz-1)projectionError=max(projectionError,max(mag(py-mesh.C()[i].y()),mag(pz-mesh.C()[i].z())));
   scalar hv=cellHv[i]*mesh.V()[i];cardConductance+=hv;
   for(int a=0;a<4;a++){int row=ids[i][a];scalar wa=weights[i][a];Hsum[row]+=hv*wa;
    for(int c=0;c<4;c++){int col=ids[i][c];int oy=(col%nb)%ny-(row%nb)%ny,oz=(col%nb)/ny-(row%nb)/ny;M[9*row+(oz+1)*3+oy+1]+=hv*wa*weights[i][c];}}

  }
  }
  if(cardConductance<=SMALL)FatalErrorInFunction<<"No thermal conductance for card "<<card<<exit(FatalError);
  scalar total=0;
  for(int iz=0;iz<nz;iz++)for(int iy=0;iy<ny;iy++)
  {
   scalar y=(iy+.5)*dy-w/2,z=(iz+.5)*dz;
   scalar s=uniformPart/(w*len)+(1-uniformPart)*Foam::exp(-.5*sqr(y/sy)-.5*sqr((z-sourceCentre*len)/sz))/(2*constant::mathematical::pi*sy*sz);
   int b=card*nb+iz*ny+iy;q[b]=s*dy*dz;total+=q[b];
  }
  for(int b=card*nb;b<(card+1)*nb;b++)q[b]*=P/total;
 }
 Pstream::listReduce(Hsum,sumOp<scalar>());Pstream::listReduce(M,sumOp<scalar>());
 // Closure and heat sources share exactly the same bins/weights. Adiabatic
 // outer base edges; source distribution is an explicit assumed scenario.
 H.correctBoundaryConditions();alpha.correctBoundaryConditions();
 const bool isothermal=props.getOrDefault<bool>("isothermalBase",false);
 scalar lastEnergy=GREAT,change=GREAT,fluidChange=GREAT,airRms=GREAT,heatedRms=GREAT,exchangeChangeBound=GREAT;int finalIter=0;
 label worstCell=0;
 for(int iter=0;iter<maxCouplingIterations;iter++)
 {
  scalarField previousAir(T.primitiveField());
  HT=0;forAll(bin,i)if(bin[i]>=0)for(int a=0;a<4;a++)HT[ids[i][a]]+=weights[i][a]*cellHv[i]*mesh.V()[i]*T[i];Pstream::listReduce(HT,sumOp<scalar>());
  scalarField previous(base);
  if(isothermal)for(int card=0;card<2;card++){scalar h=0,ht=0,power=0;for(int b=card*nb;b<(card+1)*nb;b++){h+=Hsum[b];ht+=HT[b];power+=q[b];}for(int b=card*nb;b<(card+1)*nb;b++)base[b]=(power+ht)/h;}
  for(int sweep=0;sweep<(isothermal?0:3000);sweep++)
  {
   scalar maxUpdate=0;
   for(int card=0;card<2;card++)for(int iz=0;iz<nz;iz++)for(int iy=0;iy<ny;iy++)
   {
    int b=card*nb+iz*ny+iy;scalar a=M[9*b+4],rhs=q[b]+HT[b];
    for(int oz=-1;oz<=1;oz++)for(int oy=-1;oy<=1;oy++)if((oz||oy)&&iy+oy>=0&&iy+oy<ny&&iz+oz>=0&&iz+oz<nz)rhs-=M[9*b+(oz+1)*3+oy+1]*base[b+oz*ny+oy];
    if(iy>0){a+=Gy;rhs+=Gy*base[b-1];}if(iy+1<ny){a+=Gy;rhs+=Gy*base[b+1];}
    if(iz>0){a+=Gz;rhs+=Gz*base[b-ny];}if(iz+1<nz){a+=Gz;rhs+=Gz*base[b+ny];}
    scalar next=rhs/max(a,SMALL);maxUpdate=max(maxUpdate,mag(next-base[b]));base[b]=next;
   }
   if(maxUpdate<1e-8)break;
  }
  change=0;forAll(base,b)change=max(change,mag(base[b]-previous[b]));
  forAll(bin,i){Tb[i]=inletT;if(bin[i]>=0){Tb[i]=0;for(int a=0;a<4;a++)Tb[i]+=weights[i][a]*base[ids[i][a]];}}
  Tb.correctBoundaryConditions();
  for(int nonOrth=0;nonOrth<3;nonOrth++)
  {
   fvScalarMatrix eq(fvm::div(phi,T)-fvm::laplacian(alpha,T)+fvm::Sp(H,T)==H*Tb);
   eq.relax(couplingRelaxation);
   eq.solve();
  }
  scalarField deltaAir(mag(T.primitiveField()-previousAir));fluidChange=gMax(deltaAir);worstCell=findMax(deltaAir);
  const scalarField& vv=mesh.V();airRms=Foam::sqrt(gSum(vv*sqr(deltaAir))/gSum(vv));
  scalar hDelta=0,hTotal=0,hAbsolute=0;forAll(bin,i)if(bin[i]>=0){scalar weight=H[i]*rhoCp*mesh.V()[i];hDelta+=weight*sqr(deltaAir[i]);hAbsolute+=weight*deltaAir[i];hTotal+=weight;}
  heatedRms=Foam::sqrt(hDelta/max(SMALL,hTotal));
  exchangeChangeBound=hAbsolute+hTotal*change;
  scalar heat=0;forAll(bin,i)if(bin[i]>=0)heat+=cellHv[i]*mesh.V()[i]*(Tb[i]-T[i]);reduce(heat,sumOp<scalar>());
  lastEnergy=mag(heat-2*P)/(2*P);finalIter=iter;
  if(iter%10==0)Info<<"THERMAL "<<iter<<" baseChangeK "<<change<<" airChangeK "<<fluidChange<<" airRmsK "<<airRms<<" heatedRmsK "<<heatedRms<<" worstCell "<<mesh.C()[worstCell]<<" worstT "<<T[worstCell]<<" worstH "<<H[worstCell]<<" fluidHeatW "<<heat<<" balance "<<lastEnergy<<endl;
  if(iter>10&&change<1e-5&&airRms<.001&&heatedRms<.001&&fluidChange<.1&&exchangeChangeBound<2*P*1e-5&&lastEnergy<1e-5)break;
 }
 HT=0;forAll(bin,i)if(bin[i]>=0)for(int a=0;a<4;a++)HT[ids[i][a]]+=weights[i][a]*cellHv[i]*mesh.V()[i]*T[i];
 std::ofstream coeff((runTime.path()/"base-coupling.json").c_str());coeff<<std::setprecision(15)<<"{\"ny\":"<<ny<<",\"nz\":"<<nz<<",\"Gy\":"<<Gy<<",\"Gz\":"<<Gz<<",\"partition_error\":"<<partitionError<<",\"linear_projection_error_m\":"<<projectionError;
 const char* keys[]={"Hsum","HT","q","base","exchange_coeffs"};const scalarField* arrays[]={&Hsum,&HT,&q,&base,&M};
 for(int a=0;a<5;a++){coeff<<",\""<<keys[a]<<"\":[";forAll((*arrays[a]),i)coeff<<(i?",":"")<<(*arrays[a])[i];coeff<<"]";}coeff<<"}";
 T.rename("T");T.instance()=runTime.timeName();T.write();Tb.write();H.write();
 scalar outEnergy=0;
 forAll(phi.boundaryField(),patch)
 {
  const auto& ph=phi.boundaryField()[patch];const auto& tp=T.boundaryField()[patch];
  if(tp.coupled())continue; // cyclic fan baffles (serial run): both sides cancel, and coupled snGrad() is not implemented
  scalar flow=gSum(ph),enthalpy=gSum(ph*(tp-inletT))*rhoCp;
  scalar conduction=-gSum(alpha.boundaryField()[patch]*tp.snGrad()*mesh.magSf().boundaryField()[patch])*rhoCp;
  if(mesh.boundary()[patch].type()!="processor")Info<<"PATCH "<<mesh.boundary()[patch].name()<<" Q "<<flow<<" enthalpyW "<<enthalpy<<" conductionW "<<conduction<<endl;
  outEnergy+=enthalpy+conduction;
 }
 scalar relativeU=-1;
 if(props.found("referenceFlowTime")){word oldTime=Foam::name(props.get<label>("referenceFlowTime"));volVectorField oldU(IOobject("U",oldTime,mesh,IOobject::MUST_READ,IOobject::NO_WRITE),mesh);const scalarField& vv=mesh.V();relativeU=Foam::sqrt(gSum(vv*magSqr(U.primitiveField()-oldU.primitiveField()))/max(SMALL,gSum(vv*magSqr(U.primitiveField()))));}
 std::ofstream f((runTime.path()/"thermal-results.json").c_str());
 f<<std::setprecision(12)<<"{\"flow_time\":\""<<runTime.timeName()<<"\",\"fluid_change_K\":"<<fluidChange<<",\"air_min_K\":"<<gMin(T.primitiveField())<<",\"air_max_K\":"<<gMax(T.primitiveField())<<",\"relative_velocity_change_from_reference\":"<<relativeU<<",\"iterations\":"<<finalIter<<",\"base_change_K\":"<<change<<",\"exchange_energy_error\":"<<lastEnergy<<",\"boundary_energy_W\":"<<outEnergy<<",\"power_each_W\":"<<P<<",\"inlet_T_K\":"<<inletT<<",\"rhoCp\":"<<rhoCp<<",\"ny\":"<<ny<<",\"nz\":"<<nz<<",\"cards\":[";
 for(int card=0;card<2;card++)
 {
  scalar maxT=-GREAT,meanT=0,sourceMeanT=0;
  for(int b=card*nb;b<(card+1)*nb;b++){maxT=max(maxT,base[b]);meanT+=base[b]/nb;sourceMeanT+=q[b]*base[b]/P;}
  scalar flow=0;label zi=mesh.cellZones().findZoneID("card"+Foam::name(card)+"path0");for(const label i:mesh.cellZones()[zi])flow+=U[i].z()*mesh.V()[i]/len;
  reduce(flow,sumOp<scalar>());
  scalar qBoundary=0;
  label patchI=mesh.boundaryMesh().findPatchID(cardExitPatch[card]);
  if(patchI>=0){const auto& pp=phi.boundaryField()[patchI];const auto& centres=mesh.Cf().boundaryField()[patchI];scalar cx=card==0?-.03048:.03048;forAll(pp,j)if(centres[j].x()>cx-.0054)qBoundary+=pp[j];}
  scalarField qRows(ny,0),rowVolumes(ny,0);forAll(bin,i)if(cellPath[i]==0&&bin[i]>=card*nb&&bin[i]<(card+1)*nb)for(int a=0;a<4;a++){int row=(ids[i][a]-card*nb)%ny;scalar vol=weights[i][a]*mesh.V()[i];qRows[row]+=U[i].z()*vol/len;rowVolumes[row]+=vol;}
  f<<(card?",":"")<<"{\"peak_base_K\":"<<maxT<<",\"mean_base_K\":"<<meanT<<",\"source_weighted_base_K\":"<<sourceMeanT<<",\"main_Q_m3s\":"<<flow<<",\"main_boundary_Q_m3s\":"<<qBoundary<<",\"flow_by_y_m3s\":[";
  for(int j=0;j<ny;j++)f<<(j?",":"")<<qRows[j];f<<"],\"row_volumes_m3\":[";for(int j=0;j<ny;j++)f<<(j?",":"")<<rowVolumes[j];f<<"],\"base_grid_K\":[";
  for(int b=card*nb;b<(card+1)*nb;b++)f<<(b%nb?",":"")<<base[b];f<<"],\"paths\":[";
  forAll(pathHvol,path)
  {
   scalar heat=0,conductance=0,volume=0,pathFlow=0;
   forAll(bin,i)if(cellPath[i]==path&&bin[i]>=card*nb&&bin[i]<(card+1)*nb)
   {scalar v=mesh.V()[i];heat+=cellHv[i]*v*(Tb[i]-T[i]);conductance+=cellHv[i]*v;volume+=v;pathFlow+=U[i].z()*v/len;}
   f<<(path?",":"")<<"{\"path\":"<<path<<",\"Hvol_W_m3K\":"<<pathHvol[path]<<",\"conductance_W_K\":"<<conductance<<",\"heat_W\":"<<heat<<",\"volume_m3\":"<<volume<<",\"Q_m3s\":"<<pathFlow<<"}";
  }
  f<<"]}";
 }
 f<<"]}";
 std::ofstream diag((runTime.path()/"temperature-convergence.json").c_str());
 const bool thermalPass=change<1e-5&&airRms<.001&&heatedRms<.001&&fluidChange<.1&&exchangeChangeBound<2*P*1e-5&&lastEnergy<1e-5&&gMin(T.primitiveField())>=inletT-.01&&gMax(T.primitiveField())<=gMax(base)+.01&&mag(outEnergy-2*P)/(2*P)<1e-4;
 diag<<std::setprecision(12)<<"{\"thermal_objective_converged\":"<<(thermalPass?"true":"false")<<",\"air_pointwise_1e5_converged\":"<<(fluidChange<1e-5?"true":"false")<<",\"exchange_change_bound_W\":"<<exchangeChangeBound<<",\"air_rms_change_K\":"<<airRms<<",\"heated_air_rms_change_K\":"<<heatedRms<<",\"max_air_change_K\":"<<fluidChange<<",\"worst_cell_exchange_rate_s\":"<<H[worstCell]<<",\"worst_cell_temperature_K\":"<<T[worstCell]<<",\"worst_cell_xyz_m\":["<<mesh.C()[worstCell].x()<<","<<mesh.C()[worstCell].y()<<","<<mesh.C()[worstCell].z()<<"]}";
 Info<<"THERMAL_END iterations "<<finalIter<<" energyOutW "<<outEnergy<<" baseChangeK "<<change<<endl;
 return thermalPass?0:2;
}
